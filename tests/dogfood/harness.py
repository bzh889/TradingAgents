"""Dogfood harness for `tradingagents analyze` with --executor claude-code.
Encoding-safe on Windows cp950 — see top of __main__ guard for stdout reconfigure.

Drives the questionary selector via prompt_toolkit's create_pipe_input
(no subprocess, no PTY — questionary is a thin wrapper over prompt_toolkit,
so we can in-process fake-stdin it).

The two typer.prompt Y/N at the end + ticker/date prompts are driven via
sys.stdin monkey-patch (typer.prompt -> click -> visible_prompt_func uses
sys.stdin).

Once selectors are answered, the real graph runs — meaning real
ClaudeCodeExecutor subprocess invocations against the user's Claude Code
subscription. So this harness DOES burn quota.
"""
from __future__ import annotations

import io
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@contextmanager
def piped_stdin(text):
    orig = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = orig


def run_selector_path(
    executor="claude-code",
    ticker="SPY",
    analysis_date=None,
    analyst_indices=(0,),  # tuple of indices to TOGGLE in checkbox order
    depth_index=0,
    provider_index=0,
    shallow_model_index=0,
    deep_model_index=0,
    portfolio_context="",
    display_report=False,
    transcript_path=None,
    timeout_seconds=600,
):
    if analysis_date is None:
        analysis_date = datetime.now().strftime("%Y-%m-%d")

    cli_mode = executor != "api"

    DOWN = "\x1b[B"
    ENTER = "\r"
    SPACE = " "

    keys_parts = []

    # Step 1: execution mode (questionary.select)
    exec_choices = ["api", "claude-code", "codex", "gemini"]
    exec_idx = exec_choices.index(executor)
    keys_parts.append(DOWN * exec_idx + ENTER)

    # Step 3: output language (questionary.select, English = first)
    keys_parts.append(ENTER)

    # Step 4: analysts checkbox — toggle each desired index in order,
    # cursor starts at 0 and moves DOWN to each target before toggling.
    cursor = 0
    for idx in analyst_indices:
        diff = idx - cursor
        if diff > 0:
            keys_parts.append(DOWN * diff)
        keys_parts.append(SPACE)
        cursor = idx
    keys_parts.append(ENTER)

    # Step 5: research depth (questionary.select)
    keys_parts.append(DOWN * depth_index + ENTER)

    # Steps 6/7/8: provider + models + effort. New CLI mode SKIPS these
    # entirely. API mode still asks. Keep the old keystrokes only for API mode.
    if not cli_mode:
        keys_parts.append(DOWN * provider_index + ENTER)
        keys_parts.append(DOWN * shallow_model_index + ENTER)
        keys_parts.append(DOWN * deep_model_index + ENTER)
        provider_names = [
            "openai", "google", "anthropic", "xai", "deepseek",
            "deepseek", "qwen", "glm", "openrouter", "azure", "ollama",
        ]
        selected_provider = provider_names[provider_index]
        if selected_provider in ("google", "openai", "anthropic"):
            keys_parts.append(ENTER)

    # Post-run: display_report questionary.confirm (default No).
    # ENTER alone confirms default (No). Press "y" + ENTER to display.
    if display_report:
        keys_parts.append("y" + ENTER)
    else:
        keys_parts.append(ENTER)

    keystrokes = "".join(keys_parts)

    # Dogfood-found-bug #2: TradingAgentsGraph.__init__ still instantiates LLM
    # clients (deep + quick) from the selected provider even when executor is
    # claude-code / codex / gemini. Subscription users may not have any LLM
    # API key. Workaround: inject a dummy key so client construction succeeds;
    # the key is never used because the executor intercepts every node call.
    # The proper fix is to skip LLM build entirely in CLI mode — left as a
    # follow-up scope (separate spec).
    os.environ.setdefault("OPENAI_API_KEY", "sk-dogfood-dummy-not-used-in-cli-mode")
    # NOTE: do NOT inject ANTHROPIC_API_KEY — ClaudeCodeExecutor strips it from
    # subprocess env anyway (so the subscription keychain OAuth wins), but the
    # parent process also need not see a fake key.
    os.environ.setdefault("GOOGLE_API_KEY", "dogfood-dummy")

    # typer.prompt feeds (read from sys.stdin pipe):
    #   1. ticker
    #   2. analysis_date
    #   3. portfolio_context (Step 3b — empty line skips)
    # NOTE: the old save-report / save-path prompts are GONE in the new UX;
    # the consolidated report auto-saves to results_dir.
    typer_input = (
        f"{ticker}\n"
        f"{analysis_date}\n"
        f"{portfolio_context}\n"
    )

    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    result = {
        "status": "unknown",
        "error": None,
        "executor_picked": executor,
        "elapsed_seconds": 0.0,
        "transcript_tail": "",
    }

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    started = time.time()

    def run():
        try:
            for mod in list(sys.modules):
                if mod.startswith("cli.") or mod == "cli":
                    del sys.modules[mod]
            from cli.main import analyze as analyze_fn
            analyze_fn(checkpoint=False, clear_checkpoints=False, executor=None)
            result["status"] = "ok"
        except SystemExit as e:
            result["status"] = "system_exit"
            result["error"] = f"SystemExit({e.code})"
        except Exception as e:
            result["status"] = "exception"
            result["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:3000]}"

    # prompt_toolkit's create_app_session is THREAD-LOCAL. The questionary calls
    # run inside the worker thread, so the session must be entered INSIDE that
    # thread. We do that by wrapping `run` with the context-manager dance.
    with create_pipe_input() as pt_input:
        with piped_stdin(typer_input):
            orig_stdout, orig_stderr = sys.stdout, sys.stderr
            sys.stdout = captured_stdout
            sys.stderr = captured_stderr
            try:
                def threaded_run():
                    with create_app_session(input=pt_input, output=DummyOutput()):
                        run()
                t = threading.Thread(target=threaded_run, daemon=True)
                t.start()
                # Give the thread a moment to enter app_session before sending.
                time.sleep(0.1)
                pt_input.send_text(keystrokes)
                t.join(timeout=timeout_seconds)
                if t.is_alive():
                    result["status"] = "timeout"
                    result["error"] = f"harness exceeded {timeout_seconds}s"
            finally:
                sys.stdout = orig_stdout
                sys.stderr = orig_stderr

    result["elapsed_seconds"] = round(time.time() - started, 2)

    stdout_text = captured_stdout.getvalue()
    stderr_text = captured_stderr.getvalue()
    tail = (stdout_text + "\n--STDERR--\n" + stderr_text)[-4000:]
    result["transcript_tail"] = tail

    if transcript_path:
        Path(transcript_path).write_text(
            f"=== DOGFOOD RUN {datetime.now().isoformat()} ===\n"
            f"executor={executor} ticker={ticker} date={analysis_date}\n"
            f"analyst_indices={analyst_indices} depth_index={depth_index} "
            f"provider_index={provider_index}\n"
            f"--- KEYSTROKES (repr) ---\n{keystrokes!r}\n"
            f"--- TYPER INPUT ---\n{typer_input}\n"
            f"--- RESULT ---\n{result['status']} | error={result['error']}\n"
            f"--- STDOUT ---\n{stdout_text}\n"
            f"--- STDERR ---\n{stderr_text}\n",
            encoding="utf-8",
        )

    return result


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--executor", default="claude-code")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--date", default=None)
    parser.add_argument(
        "--analysts",
        default="0",
        help="Comma-separated indices into Step 4 checkbox order (market=0, social=1, news=2, fundamentals=3). Default '0' = market only.",
    )
    parser.add_argument("--depth", type=int, default=0)
    parser.add_argument("--provider", type=int, default=0)
    parser.add_argument("--shallow-model", type=int, default=0)
    parser.add_argument("--deep-model", type=int, default=0)
    parser.add_argument("--portfolio-context", default="")
    parser.add_argument("--display", action="store_true", help="Display full report after run")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--transcript",
        default=str(ROOT / "tests" / "dogfood" / "_last_transcript.txt"),
    )
    args = parser.parse_args()

    analyst_indices = tuple(int(x) for x in args.analysts.split(",") if x.strip())
    res = run_selector_path(
        executor=args.executor,
        ticker=args.ticker,
        analysis_date=args.date,
        analyst_indices=analyst_indices,
        depth_index=args.depth,
        provider_index=args.provider,
        shallow_model_index=args.shallow_model,
        deep_model_index=args.deep_model,
        portfolio_context=args.portfolio_context,
        display_report=args.display,
        timeout_seconds=args.timeout,
        transcript_path=Path(args.transcript),
    )
    print(f"STATUS: {res['status']}")
    print(f"ELAPSED: {res['elapsed_seconds']}s")
    if res["error"]:
        print("ERROR (first 800 chars):")
        print(res["error"][:800])
    print(f"TRANSCRIPT_TAIL ({len(res['transcript_tail'])} chars):")
    print(res["transcript_tail"][-2000:])
