"""Fetch exact upstream inputs and apply reviewed patches inside a new private directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / 'lock.json').read_text(encoding='utf-8'))
def io_path(path):
    # Extended private paths avoid Windows MAX_PATH without registry changes.
    value = str(path.resolve())
    return Path('\\\\?\\' + value) if os.name == 'nt' and not value.startswith('\\\\?\\') else path


sha = lambda p: hashlib.sha256(io_path(p).read_bytes()).hexdigest()
GIT = ['git', '-c', 'http.sslBackend=openssl', '-c', 'http.version=HTTP/1.1', '-c', 'core.longpaths=true']


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def download(entry, cache, digest='sha256'):
    path = cache / entry['url'].rsplit('/', 1)[-1]
    if not path.exists():
        urllib.request.urlretrieve(entry['url'], path)
    if sha(path) != entry[digest]:
        raise ValueError(f'Hash mismatch: {path}; keep the file for investigation')
    return path


def extract(archive, root, strip):
    root.mkdir(parents=True, exist_ok=False)
    def target(name):
        relative = Path(*Path(name.replace('\\', '/')).parts[strip:])
        result = (root / relative).resolve()
        if not result.is_relative_to(root.resolve()):
            raise ValueError(f'Unsafe archive entry: {name}')
        return result if relative.parts else None
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                destination = target(member.filename)
                if destination is None:
                    continue
                destination = io_path(destination)
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(member) as src, destination.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive) as package:
            for member in package:
                destination = target(member.name)
                if destination is None:
                    continue
                destination = io_path(destination)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(member) as src, destination.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                else:
                    raise ValueError(f'Unsupported archive link/type: {member.name}')



def seed_lfs_objects(reference, checkout):
    # The reference's Git LFS cache contains content-addressed assets, not working files.
    # Seed only complete objects verified by their OID before the locked checkout runs.
    directory = reference / '.git/lfs/objects'
    if not directory.is_dir():
        return
    target = checkout / '.git/lfs/objects'
    count = 0
    for path in directory.glob('*/*/*'):
        oid = path.name
        if (len(oid) != 64 or any(c not in '0123456789abcdef' for c in oid)
                or path.parent.name != oid[2:4] or path.parent.parent.name != oid[:2]):
            continue
        if not path.is_file() or sha(path) != oid:
            raise ValueError(f'Invalid content-addressed Git LFS object: {path}')
        destination = target / oid[:2] / oid[2:4] / oid
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        count += 1
    if count:
        print(f'Seeded {count} verified Git LFS objects for {checkout.name}.', flush=True)


def clone(entry, path, reference=None):
    if reference is not None:
        # Copy committed objects, never the reference working tree or build files.
        subprocess.run(GIT + ['cat-file', '-e', entry['commit'] + '^{commit}'], cwd=reference, check=True)
        run(*GIT, 'clone', '--no-checkout', '--no-hardlinks', str(reference), str(path))
        run(*GIT, 'remote', 'set-url', 'origin', entry['url'], cwd=path)
        seed_lfs_objects(reference, path)
    else:
        run(*GIT, 'clone', '--no-checkout', entry['url'], str(path))
    run(*GIT, 'checkout', '--detach', entry['commit'], cwd=path)
    actual = subprocess.check_output(GIT + ['rev-parse', 'HEAD'], cwd=path, text=True).strip()
    if actual != entry['commit']:
        raise ValueError(f'Wrong checkout: {path}')


def source_identity(work):
    source = work / 'source'
    result = {}
    commits = {'.': LOCK['upstream']['commit'], **LOCK['upstream']['submodules']}
    for relative, expected in commits.items():
        root = source / relative
        commit = subprocess.check_output(GIT + ['rev-parse', 'HEAD'], cwd=root, text=True).strip()
        if commit != expected:
            raise ValueError(f'Wrong source HEAD: {relative}')
        names = subprocess.check_output(GIT + ['ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
        files = {name: sha(root / name) for name in names if name and io_path(root / name).is_file()}
        extra = subprocess.check_output(GIT + ['ls-files', '--others', '--exclude-standard', '-z'], cwd=root)
        if extra:
            raise ValueError(f'Untracked source input in {relative}: {extra[:200]!r}')
        result[relative] = {'commit': commit, 'tracked_sha256': files}
    return result


def tree_identity(root):
    root = io_path(root)
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(bytes.fromhex(sha(path)))
    return digest.hexdigest()


def dependency_identity(work):
    result = {}
    for entry in LOCK['git_dependencies']:
        root = work / 'deps' / (entry['name'] + '-src')
        commit = subprocess.check_output(GIT + ['rev-parse', 'HEAD'], cwd=root, text=True).strip()
        if commit != entry['commit']:
            raise ValueError(f'Dependency HEAD changed: {entry["name"]}')
        names = subprocess.check_output(GIT + ['ls-files', '-z'], cwd=root).decode().split('\0')
        hashes = {n: sha(root / n) for n in names if n and io_path(root / n).is_file()}
        result[entry['name']] = {'commit': commit, 'tracked_tree_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}
    return result


def patch_touched_paths(patch_path):
    paths = set()
    for line in patch_path.read_text(encoding='utf-8').splitlines():
        if not line.startswith(('--- ', '+++ ')):
            continue
        name = line[4:].split('\t', 1)[0]
        if name == '/dev/null':
            continue
        if not name.startswith(('a/', 'b/')):
            raise ValueError(f'Unexpected patch path: {name}')
        parts = name[2:].split('/')
        if not all(parts) or any(part in ('.', '..') for part in parts) or ':' in parts[0]:
            raise ValueError(f'Unsafe patch path: {name}')
        paths.add(Path(*parts))
    if not paths:
        raise ValueError(f'Patch has no source paths: {patch_path}')
    return paths


def verify_applied_patches_in_scratch(work):
    # Patches may overlap. Unapply the actual sequence in reverse, rather than
    # independently checking every historical patch against the final source.
    work = work.resolve()
    scratch = Path(tempfile.mkdtemp(prefix='patch-reverse-', dir=work)).resolve()
    if not scratch.is_relative_to(work) or scratch == work:
        raise ValueError('Temporary patch-verification path escaped its work root')
    try:
        touched = set()
        for patch in LOCK['patches']:
            touched.update(patch_touched_paths(HERE / patch['file']))
        source = (work / 'source').resolve()
        for relative in sorted(touched):
            original = source / relative
            if not original.resolve().is_relative_to(source):
                raise ValueError(f'Patch input escaped source: {relative}')
            if io_path(original).exists():
                if not io_path(original).is_file():
                    raise ValueError(f'Patch input is not a regular file: {relative}')
                destination = scratch / relative
                io_path(destination.parent).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(io_path(original), io_path(destination))
        for patch in reversed(LOCK['patches']):
            path = str((HERE / patch['file']).resolve())
            run(*GIT, 'apply', '--reverse', '--check', path, cwd=scratch)
            run(*GIT, 'apply', '--reverse', path, cwd=scratch)
    finally:
        # Resolve and verify the deletion target before recursive cleanup.
        target = scratch.resolve()
        if not target.is_relative_to(work) or target == work:
            raise ValueError('Refusing scratch cleanup outside the work root')
        shutil.rmtree(io_path(target))


def verify_work(work):
    record = json.loads((work / 'prepared_inputs.json').read_text(encoding='utf-8'))
    if record['lock_sha256'] != sha(HERE / 'lock.json') or record['common_only']:
        raise ValueError('Work directory is not a Windows preparation with the current lock.')
    if source_identity(work) != record['source']:
        raise ValueError('Prepared tracked source/submodule files changed before build.')
    if dependency_identity(work) != record['dependencies']:
        raise ValueError('Prepared dependency tracked files changed before build.')
    for relative, digest in record['archive_trees'].items():
        if tree_identity(work / relative) != digest:
            raise ValueError(f'Prepared archive input changed: {relative}')
    verify_applied_patches_in_scratch(work)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--common-only', action='store_true', help='Only source + general indexed-GPU fixes; no Windows inputs')
    parser.add_argument('--verify-only', action='store_true', help='Check committed LF patch bytes without fetching/building')
    parser.add_argument('--verify-work-dir', type=Path, help='Check prepared tracked source identity, dependency HEADs and applied patches')
    parser.add_argument('--download-cache', type=Path, help='Read existing official archives here, always checking locked SHA')
    parser.add_argument('--source-reference', type=Path, help='Copy Git objects from this upstream checkout, never working files')
    parser.add_argument('--dependency-reference', type=Path, help='Copy Git objects from NAME-src repos in this directory')
    args = parser.parse_args()
    for patch in LOCK['patches']:
        path = HERE / patch['file']
        if b'\r' in path.read_bytes() or sha(path) != patch['sha256']:
            raise ValueError(f'Patch content/hash mismatch: {path}')
    if args.verify_only:
        print('All locked LF patch hashes match.')
        return
    if args.verify_work_dir:
        verify_work(args.verify_work_dir.resolve())
        print('Prepared source identity, dependency commits and applied patches match.')
        return
    if args.work_dir is None:
        parser.error('--work-dir is required')
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)  # Never reset/delete an existing checkout.
    cache = args.download_cache.resolve() if args.download_cache else work / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    source = work / 'source'
    clone(LOCK['upstream'], source, args.source_reference)
    run(*GIT, 'submodule', 'init', cwd=source)
    for path, commit in LOCK['upstream']['submodules'].items():
        reference = args.source_reference / path if args.source_reference else None
        clone({'url': LOCK['upstream']['submodule_urls'][path], 'commit': commit}, source / path, reference)
        if (source / path / '.gitmodules').exists():
            run(*GIT, 'submodule', 'init', cwd=source / path)
    for patch in LOCK['patches']:
        if patch['group'] == 'windows' and args.common_only:
            continue
        run('git', 'apply', '--check', str(HERE / patch['file']), cwd=source)
        run('git', 'apply', str(HERE / patch['file']), cwd=source)
    if args.common_only:
        print(f'Common patched source ready: {source}. Linux build/runtime validation is separate.')
        return
    deps = work / 'deps'
    deps.mkdir()
    for dependency in LOCK['git_dependencies']:
        reference = args.dependency_reference / (dependency['name'] + '-src') if args.dependency_reference else None
        clone(dependency, deps / (dependency['name'] + '-src'), reference)
    for entry in LOCK['archives']:
        extract(download(entry, cache), deps / (entry['name'] + '-src'), entry['strip'])
    cuda = work / 'cuda'
    for entry in LOCK['cuda_components']:
        staging = work / ('unpack-' + entry['component'])
        extract(download(entry, cache), staging, 1)
        shutil.copytree(staging, cuda, dirs_exist_ok=True)
    runtime = LOCK['runtime_physx']
    extract(download(runtime, cache, 'archive_sha256'), work / 'physx-runtime', 0)
    for name, digest in runtime['dll_sha256'].items():
        if sha(work / 'physx-runtime' / name) != digest:
            raise ValueError(f'PhysX DLL mismatch: {name}')
    record = {'lock_sha256': sha(HERE / 'lock.json'), 'common_only': False,
              'source': source_identity(work),
              'dependencies': dependency_identity(work),
              'archive_trees': {relative: tree_identity(work / relative) for relative in ('deps/physx5-src', 'deps/oidn-src', 'cuda', 'physx-runtime')}}
    (work / 'prepared_inputs.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(f'Private inputs prepared at {work}; no system/environment packages changed.')


if __name__ == '__main__':
    main()
