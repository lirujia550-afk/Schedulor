"""Refresh 35 days of iCloud digest events; no API key or model call required."""
import json
import agent
if __name__ == '__main__':
    result = agent.sync_calendar()
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result['ok'] else 1)
