"""Trusted tool-free inference entry point, executed only inside bubblewrap."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, '/home/Untergame/tamtam-origin/hermes-agent')

def main():
    request = json.load(sys.stdin)
    # No host process namespace, home, collector database, reports or sessions.
    forbidden = request.get('probe_paths', []) + [
        '/home/Untergame/tamtam_again/data/tamtam.sqlite3',
        '/home/Untergame/.hermes/config.yaml', '/home/Untergame/.codex',
        '/home/Untergame/tamtam_again/reports', '/proc/1/root/home/Untergame/tamtam_again/data',
    ]
    if any(Path(p).exists() for p in forbidden):
        raise RuntimeError('Isolation boundary failed')
    try:
        Path('/runner.py').open('a').close()
    except OSError:
        pass
    else:
        raise RuntimeError('Read-only code boundary failed')
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from run_agent import AIAgent
        if request.get('probe'):
            # Build the ACTUAL runtime and verify its capabilities, without inference.
            agent = AIAgent(model=request['model'], provider='openai-codex',
                            api_key='probe-not-a-credential', base_url='https://chatgpt.com/backend-api/codex',
                            api_mode='codex_responses', enabled_toolsets=[], max_iterations=1,
                            skip_context_files=True, skip_memory=True, skip_background_review=True,
                            quiet_mode=True, load_soul_identity=False)
        else:
            from hermes_cli.runtime_provider import resolve_runtime_provider
            runtime = resolve_runtime_provider(requested='openai-codex', target_model=request['model'])
            agent = AIAgent(model=request['model'], provider=runtime['provider'],
                            api_key=runtime.get('api_key'), base_url=runtime.get('base_url'),
                            api_mode=runtime.get('api_mode'), credential_pool=runtime.get('credential_pool'),
                            enabled_toolsets=[], max_iterations=1, max_tokens=request['max_output_tokens'],
                            reasoning_config={'effort': 'low'}, fallback_model=None,
                            skip_context_files=True, skip_memory=True, skip_background_review=True,
                            quiet_mode=True, load_soul_identity=False)
        if agent.tools or agent.valid_tool_names:
            raise RuntimeError('Tool-free inference boundary failed')
        if request.get('probe'):
            result = {'isolation_verified': True, 'tools': 0, 'model': request['model']}
        else:
            run = agent.run_conversation(request['prompt'])
            result = {'response': run.get('final_response', ''), 'failed': bool(run.get('failed')),
                      'usage': {'input_tokens': agent.session_prompt_tokens,
                                'output_tokens': agent.session_completion_tokens,
                                'cost_usd': agent.session_estimated_cost_usd,
                                'cost_status': agent.session_cost_status,
                                'api_calls': run.get('api_calls')}}
        agent.close()
    print(json.dumps(result))

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never leak credentials or provider tracebacks to parent logs.
        print(json.dumps({'failed': True, 'error_type': type(exc).__name__,
                          'missing_module': exc.name if isinstance(exc, ModuleNotFoundError) else None}))
        sys.exit(2)
