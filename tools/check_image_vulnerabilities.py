"""Report all severities; fail CI on fixable HIGH/CRITICAL findings."""
import json
import os
import sys
from collections import Counter
from pathlib import Path


def summarize(report):
    findings = [row for result in report.get('Results', [])
                for row in (result.get('Vulnerabilities') or [])]
    counts = Counter(row.get('Severity', 'UNKNOWN') for row in findings)
    blocking = [row for row in findings if row.get('Severity') in ('HIGH', 'CRITICAL')
                and row.get('FixedVersion')]
    lines = ['Image vulnerability audit: ' + json.dumps(dict(counts), sort_keys=True),
             f'Fixable HIGH/CRITICAL findings: {len(blocking)}']
    for row in findings:
        if row.get('Severity') not in ('HIGH', 'CRITICAL'):
            continue
        lines.append(' | '.join(str(row.get(key) or '-') for key in
                               ('Severity', 'VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion')))
    return '\n'.join(lines), bool(blocking)


if __name__ == '__main__':
    report = json.loads(Path(sys.argv[1]).read_text())
    text, blocked = summarize(report)
    print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('### Image vulnerability audit\n\n```text\n' + text + '\n```\n')
    sys.exit(1 if blocked else 0)
