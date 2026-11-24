"""Monitor one owned checker tree and keep the original console streams separate."""
import argparse
import datetime
import hashlib
import json
import subprocess
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sample():
    line = subprocess.check_output([
        'nvidia-smi', '--query-gpu=memory.free,memory.used,utilization.gpu',
        '--format=csv,noheader,nounits'], text=True, timeout=10).splitlines()[0]
    free, used, util = [int(field.strip()) for field in line.split(',')]
    return {'free_mib': free, 'used_mib': used, 'util_percent': util, 'time': time.time()}


def stop_tree(process):
    if process.poll() is None:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, timeout=15, check=False)
    return process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--delta-mib', type=int, required=True)
    parser.add_argument('--timeout-s', type=float, default=900)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A checker command is required')
    args.output.mkdir(parents=True, exist_ok=False)
    initial = sample()
    if initial['free_mib'] < 2048 or initial['util_percent'] >= 70:
        dump(args.output / 'resource.json', {'initial': initial, 'stopped': 'startup resource gate'})
        raise RuntimeError(f'Startup GPU resource gate failed: {initial}')
    report = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'launcher_sha256': digest(Path(__file__)), 'command': command, 'initial': initial,
              'samples': [], 'delta_limit_mib': args.delta_mib, 'stop_free_mib': 512}
    timed_out = False
    start = time.monotonic()
    with (args.output / 'stdout.txt').open('wb') as stdout, (args.output / 'stderr.txt').open('wb') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        report['owned_pid'] = process.pid
        try:
            while process.poll() is None:
                row = sample()
                row['delta_mib'] = row['used_mib'] - initial['used_mib']
                report['samples'].append(row)
                timed_out = time.monotonic() - start > args.timeout_s
                if timed_out or row['free_mib'] <= 512 or row['delta_mib'] > args.delta_mib:
                    report['stopped'] = 'timeout' if timed_out else 'resource threshold'
                    stop_tree(process)
                    break
                time.sleep(.4)
        except BaseException:
            report['stopped'] = 'monitor interruption'
            stop_tree(process)
            raise
        finally:
            report['returncode'] = process.poll()
            report['final'] = sample()
            report['max_delta_mib'] = max([row['delta_mib'] for row in report['samples']] + [0])
            report['min_free_mib'] = min([row['free_mib'] for row in report['samples']] + [initial['free_mib']])
            dump(args.output / 'resource.json', report)
            dump(args.output / 'process.json', {
                'command': command, 'returncode': report['returncode'], 'timed_out': timed_out,
                'streams_sha256': {name: digest(args.output / name) for name in ('stdout.txt', 'stderr.txt')}})
    verdict = {key: report.get(key) for key in ('returncode', 'max_delta_mib', 'min_free_mib', 'stopped')}
    print(json.dumps(verdict), flush=True)
    return 1 if report.get('stopped') else report['returncode']


if __name__ == '__main__':
    raise SystemExit(main())
