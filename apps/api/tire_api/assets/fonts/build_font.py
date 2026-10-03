"""Rebuild the packaged OFL font from its pinned, independently hashed source.

Run from the repository root:
  uv run --project apps/api --extra dev python apps/api/tire_api/assets/fonts/build_font.py --input PATH

The input is the official Google Fonts NotoSansSC[wght].ttf at SOURCE_URL.
This build tool never downloads data and is never called by a report request.
"""
import argparse
import hashlib
import json
from pathlib import Path

import fontTools
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

COMMIT = 'a85815a42757630ce188fdad368c2dfc444d4773'
SOURCE_URL = f'https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf'
SOURCE_SHA256 = 'a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da'
LICENSE_SHA256 = '1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    destination = Path(__file__).resolve().parent
    if hashlib.sha256(args.input.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise SystemExit('Official font SHA-256 mismatch; no output written.')
    if hashlib.sha256((destination / 'OFL.txt').read_bytes()).hexdigest() != LICENSE_SHA256:
        raise SystemExit('Official license SHA-256 mismatch; no output written.')
    font = TTFont(args.input, recalcTimestamp=False)
    instantiateVariableFont(font, {'wght': 400}, inplace=True, optimize=True)
    # A separately named derivative; preserve the upstream copyright/license
    # records and avoid use of the reserved font name "Source".
    names = {1: 'Tire Evidence SC', 2: 'Regular', 3: 'TireEvidenceSC-Regular;NotoSansSC;' + COMMIT[:12],
             4: 'Tire Evidence SC Regular', 6: 'TireEvidenceSC-Regular',
             16: 'Tire Evidence SC', 17: 'Regular'}
    for record in font['name'].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    for name_id, value in names.items():
        font['name'].setName(value, name_id, 3, 1, 0x409)
    if 'DSIG' in font:
        del font['DSIG']
    font.recalcTimestamp = False
    output = destination / 'TireEvidenceSC-Regular.ttf'
    font.save(output, reorderTables=True)
    font.close()
    data = output.read_bytes()
    provenance = {'upstream': 'Noto Sans SC', 'repository': 'https://github.com/google/fonts',
        'commit': COMMIT, 'source_url': SOURCE_URL, 'source_sha256': SOURCE_SHA256,
        'license': 'SIL Open Font License 1.1', 'license_file': 'OFL.txt', 'license_sha256': LICENSE_SHA256,
        'derivative': 'Tire Evidence SC Regular', 'output_file': output.name,
        'output_sha256': hashlib.sha256(data).hexdigest(), 'output_bytes': len(data),
        'transformation': {'weight': 400, 'fonttools_version': fontTools.__version__,
                           'renamed': True, 'timestamps': 'preserved', 'glyphs': 'not_subsetted_at_build'},
        'runtime': 'ReportLab embeds subsets of this local static TrueType font; no remote font requests.'}
    (destination / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output_sha256': provenance['output_sha256'], 'output_bytes': len(data)}))


if __name__ == '__main__':
    main()
