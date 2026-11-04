"""Package the submission without local databases, caches or preparation notes."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
FILES = ['README.md', 'REVIEW.md', 'SUBMISSION_NOTE.pdf', 'SUBMISSION_NOTE.md',
         'clinic.json', 'messages.json', 'expected.json', '.gitignore', '.gitattributes']


def main():
    output = ROOT / 'dist' / 'Rajat_Murhe_FiveNorthLabs_Assignment.zip'
    output.parent.mkdir(exist_ok=True)
    selected = [ROOT / name for name in FILES]
    for directory in ['booking', 'scripts', 'tests']:
        selected += sorted((ROOT / directory).glob('*.py'))
    selected += [ROOT / 'artifacts' / name for name in ['first-run.json', 'first-tests.txt', 'evaluation.json', 'tests.txt', 'strict-review-before.json', 'strict-review-after.json']]
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for path in selected:
            archive.write(path, 'sunrise-dental/' + str(path.relative_to(ROOT)))
    print(f'{output}\n{len(selected)} files; {output.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
