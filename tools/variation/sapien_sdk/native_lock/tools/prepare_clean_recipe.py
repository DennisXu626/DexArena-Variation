"""Install the published v7 recipe into a fresh private build directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil


HERE = Path(__file__).resolve().parent
RECIPE = 'recipe-v6'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_file(root, relative):
    name = PurePosixPath(relative)
    if not name.parts or name.is_absolute() or '..' in name.parts or '\\' in relative or ':' in relative:
        raise ValueError(f'Invalid recipe path: {relative}')
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Recipe file is outside the bundle or missing: {relative}')
    return path


def prepare(repo, work, tools):
    if tools.resolve(strict=True) != HERE:
        raise ValueError('Use the tools directory in this published SDK bundle')
    bundle = HERE.parent
    if work == repo or work.is_relative_to(repo / 'tools') or work.is_relative_to(bundle) or bundle.is_relative_to(work):
        raise ValueError('Choose a private work directory outside the SDK source bundle')
    if work.exists() and (not work.is_dir() or any(work.iterdir())):
        raise ValueError('The private work directory must be new or empty to install the recipe')

    raw = json.loads((bundle / 'COPY_MANIFEST.json').read_text(encoding='utf-8'))
    files = raw['files_sha256']
    for relative, expected in files.items():
        if digest(source_file(bundle, relative)) != expected:
            raise ValueError(f'Published SDK bundle SHA-256 mismatch: {relative}')

    name = f'{RECIPE}/clean-recipe-manifest.json'
    manifest = json.loads(source_file(bundle, name).read_text(encoding='utf-8'))
    base_lock = repo / 'tools/variation/sapien_sdk/lock.json'
    if not base_lock.is_file() or digest(base_lock) != manifest['source_recipe_lock_sha256']:
        raise ValueError('Point --repo-root at a checkout containing the locked base SDK recipe')
    expected_files = {f'{RECIPE}/{relative}': checksum for relative, checksum in
                      manifest['output_recipe_files_sha256'].items()}
    recipe_files = {relative: checksum for relative, checksum in files.items()
                    if PurePosixPath(relative).parts[0] == RECIPE and relative != name}
    if expected_files != recipe_files or name not in files:
        raise ValueError('Published v7 recipe and copy manifests disagree')

    (work / RECIPE).mkdir(parents=True)
    for relative in sorted([name, *recipe_files]):
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file(bundle, relative), destination)
        if digest(destination) != files[relative]:
            raise ValueError(f'Copied recipe SHA-256 mismatch: {relative}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--bundle-root', type=Path, default=HERE)
    args = parser.parse_args()
    try:
        prepare(args.repo_root.resolve(strict=True), args.work_dir.resolve(), args.bundle_root)
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
