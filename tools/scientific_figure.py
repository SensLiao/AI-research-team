"""Small offline SVG-to-publication adapter for scientific illustrations.

The agent authors inert SVG and a short evidence/asset specification. This tool
checks real local inputs, exports vector PDF and RGB PNG, and emits the existing
v2 asset manifest. Geometry checks are not scientific or aesthetic approval.
No downloads, API keys, external skills, subprocesses, or original overwrites.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import platform
import re
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

from research_agent_teams.tools._manuscript_integrator_security import validate_svg

RENDERER_REF = "research_agent_teams/tools/scientific_figure.py"
ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "MIT"}
RELATIONS = {"activation", "inhibition", "conversion", "transport", "association", "context"}


class ScientificFigureError(ValueError):
    """Invalid source, unsafe path or unsuccessful publication export."""


def _fail(code: str, detail: str, *_: object) -> None:
    raise ScientificFigureError(f"{code}: {detail}")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash(value: object) -> str:
    return _sha(_canonical(value))


def _path(root: Path, ref: object) -> Path:
    name = str(ref or "").replace("\\", "/")
    if not name or ":" in name or Path(name).is_absolute() or PureWindowsPath(name).drive or ".." in Path(name).parts:
        _fail("UNSAFE_PATH", name)
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()):
        _fail("UNSAFE_PATH", name)
    for part in [target, *target.parents]:
        if part == root.parent:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            _fail("UNSAFE_PATH", f"linked path: {name}")
    if any(p.lower().startswith('.env') for p in Path(name).parts):
        _fail("UNSAFE_PATH", "credential-like path")
    return target


def _read(root: Path, row: Mapping[str, Any]) -> bytes:
    p = _path(root, row.get("ref"))
    if not p.is_file() or p.stat().st_size > 20_000_000:
        _fail("INPUT_UNAVAILABLE", str(row.get("ref")))
    data = p.read_bytes()
    if not data or _sha(data) != row.get("sha256"):
        _fail("INPUT_HASH_MISMATCH", str(row.get("ref")))
    return data


def _number(value: object, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        _fail("INVALID_DIMENSION", name)
    return float(value)


def validate_spec(run_dir: str | Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    if not isinstance(spec, Mapping):
        _fail("INVALID_SPEC", "expected an object")
    for key in ["run_id", "asset_id", "label", "purpose", "caption", "accessibility_text", "svg_source", "source_inputs", "claim_refs", "output_stem"]:
        if not spec.get(key):
            _fail("MISSING_FIELD", key)
    if not isinstance(spec['caption'], Mapping) or not isinstance(spec['svg_source'], Mapping):
        _fail('INVALID_SPEC', 'caption and svg_source must be objects')
    if not isinstance(spec['source_inputs'], list) or not all(isinstance(r, Mapping) for r in spec['source_inputs']):
        _fail('INVALID_SPEC', 'source_inputs must be a list of objects')
    if not isinstance(spec['claim_refs'], list) or not all(isinstance(r, str) and r.strip() for r in spec['claim_refs']):
        _fail('INVALID_SPEC', 'claim_refs must be a nonempty list of IDs')
    if not re.fullmatch(r"fig:[A-Za-z0-9][A-Za-z0-9:._-]*", str(spec["label"])):
        _fail("INVALID_LABEL", str(spec["label"]))
    if not spec["caption"].get("text") or not spec["caption"].get("owner_role"):
        _fail("MISSING_FIELD", "caption text/owner_role")
    width = _number(spec.get("width_mm"), 40, 250, "width_mm")
    dpi = _number(spec.get("dpi", 600), 300, 1200, "dpi")
    font_min = _number(spec.get("min_font_pt", 8), 6, 20, "min_font_pt")
    source = _read(root, spec["svg_source"])
    validate_svg(source, str(spec["svg_source"]["ref"]), fail=_fail)
    tree = ET.fromstring(source)
    if tree.tag.rsplit('}', 1)[-1] != 'svg':
        _fail("INVALID_SVG", "root is not svg")
    try:
        box = [float(x) for x in re.split(r"[ ,]+", tree.attrib["viewBox"].strip())]
        if len(box) != 4 or not all(math.isfinite(x) for x in box) or min(box[2:]) <= 0:
            raise ValueError()
    except (KeyError, ValueError):
        _fail("INVALID_SVG", "a finite, positive viewBox is required")
    height = width * box[3] / box[2]
    if height > 250 or width / 25.4 * dpi * height / 25.4 * dpi > 60_000_000:
        _fail("RENDER_BUDGET", "figure exceeds 250 mm height or 60 megapixels")
    ids = [e.attrib["id"] for e in tree.iter() if "id" in e.attrib]
    if len(ids) != len(set(ids)):
        _fail("DUPLICATE_SVG_ID", "SVG IDs must be unique")
    inputs = list(spec["source_inputs"])
    for row in inputs:
        if row.get("immutable") is not True:
            _fail("MUTABLE_INPUT", str(row.get("ref")))
        _read(root, row)
    claims = set(spec["claim_refs"])
    for edge in spec.get("relations", []):
        if edge.get("id") not in ids or edge.get("type") not in RELATIONS:
            _fail("UNBOUND_RELATION", str(edge.get("id")))
        if edge.get("support") not in {"reported", "proposed", "context"} or not edge.get("claim_refs") or not set(edge["claim_refs"]).issubset(claims):
            _fail("UNSUPPORTED_RELATION", str(edge.get("id")))
    for asset in spec.get("artwork", []):
        _read(root, asset)
        if asset.get("svg_id") not in ids:
            _fail("UNUSED_ARTWORK", str(asset.get("svg_id")))
        if asset.get("license") not in ALLOWED_LICENSES or not all(asset.get(k) for k in ["source_url", "creator", "license_url", "license_evidence"]):
            _fail("ARTWORK_PERMISSION", "item-level source, creator and licence evidence required")
        if asset["license"] != "CC0-1.0" and not asset.get("credit_text"):
            _fail("ARTWORK_CREDIT", str(asset.get("ref")))
        if asset["license"] != "CC0-1.0" and asset['credit_text'] not in spec['caption']['text']:
            _fail("ARTWORK_CREDIT", "required attribution must appear in the public figure caption")
    _path(root, spec["output_stem"])
    return {"width_mm": width, "height_mm": height, "dpi": dpi, "min_font_pt": font_min,
            "source_inputs_verified": len(inputs), "relation_bindings": len(spec.get("relations", [])),
            "scientific_review": "REQUIRED", "visual_review": "REQUIRED"}


def _environment() -> dict[str, str]:
    import fitz
    import PIL
    env = {"python": platform.python_version(), "pillow": PIL.__version__, "pymupdf": fitz.VersionBind,
           "font_set_sha256": _sha(fitz.Font('helv').buffer + fitz.Font('hebo').buffer + fitz.Font('heit').buffer)}
    env["environment_sha256"] = _hash(env)
    return env


def _expand_straight_dashes(tree: ET.Element) -> int:
    """Preserve evidential line semantics in SVG readers that ignore dash arrays.

    Expand only explicit straight M/L/H/V paths into inert short segments.
    Curved dashed paths require authored segmented geometry; never silently
    replace a proposed relationship with a solid arrow.
    """
    count = 0
    for element in list(tree.iter()):
        dash = element.attrib.get('stroke-dasharray')
        if not dash or dash == 'none':
            continue
        tokens = re.findall(r'[MLHV]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?', element.attrib.get('d', ''))
        try:
            if element.tag.rsplit('}', 1)[-1] != 'path' or tokens[0] != 'M':
                raise ValueError()
            x1, y1 = float(tokens[1]), float(tokens[2])
            if len(tokens) == 6 and tokens[3] == 'L':x2, y2 = float(tokens[4]), float(tokens[5])
            elif len(tokens) == 5 and tokens[3] == 'H':x2, y2 = float(tokens[4]), y1
            elif len(tokens) == 5 and tokens[3] == 'V':x2, y2 = x1, float(tokens[4])
            else:raise ValueError()
            values = [float(x) for x in re.split(r'[ ,]+', dash)]
            if len(values) == 1:values *= 2
            if len(values) != 2 or min(values) <= 0 or not all(math.isfinite(x) for x in values):raise ValueError()
            if float(element.attrib.get('stroke-dashoffset', 0)) != 0:raise ValueError()
        except (IndexError, ValueError):
            _fail('UNSUPPORTED_DASH_PATH', 'use explicit segments for curved or offset dashed paths')
        length = math.hypot(x2-x1, y2-y1)
        if not length or not math.isfinite(length):_fail('INVALID_DASH_PATH', 'non-finite or zero length')
        if length/sum(values)>10000:_fail('RENDER_BUDGET', 'too many dash segments')
        attrs = {k:v for k,v in element.attrib.items() if k not in {'d','stroke-dasharray','stroke-dashoffset'}}
        element.tag = '{http://www.w3.org/2000/svg}g';element.attrib.clear();element.attrib.update(attrs)
        at = 0.0
        while at < length:
            stop = min(length, at+values[0]);a=at/length;b=stop/length
            ET.SubElement(element,'{http://www.w3.org/2000/svg}path',{'d':f'M {x1+(x2-x1)*a:g} {y1+(y2-y1)*a:g} L {x1+(x2-x1)*b:g} {y1+(y2-y1)*b:g}'})
            at += sum(values)
        count += 1
    return count


def render_figure(run_dir: str | Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Render one conceptual illustration; all outputs are CREATE_NEW."""
    import fitz
    from PIL import Image
    root = Path(run_dir).resolve()
    checks = validate_spec(root, spec)
    source = _read(root, spec["svg_source"])
    tree = ET.fromstring(source)
    checks['dash_paths_preserved_as_geometry'] = _expand_straight_dashes(tree)
    tree.set("width", f'{checks["width_mm"]}mm')
    tree.set("height", f'{checks["height_mm"]}mm')
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    svg = ET.tostring(tree, encoding='utf-8')
    doc = fitz.open(stream=svg, filetype='svg')
    pdf = fitz.open('pdf', doc.convert_to_pdf())
    page = pdf[0]
    if abs(page.rect.width * 25.4 / 72 - checks['width_mm']) > .15:
        _fail("PAGE_SIZE", "SVG exporter did not preserve physical width")
    spans = [s for b in page.get_text('dict', clip=fitz.INFINITE_RECT(), flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_MEDIABOX_CLIP)['blocks']
             if b['type'] == 0 for l in b['lines'] for s in l['spans'] if s['text'].strip()]
    if not spans:
        _fail("NO_EDITABLE_TEXT", "figure labels must remain text")
    checks['smallest_exported_font_pt'] = min(s['size'] for s in spans)
    if checks['smallest_exported_font_pt'] + .05 < checks['min_font_pt']:
        _fail("SMALL_TEXT", f'{checks["smallest_exported_font_pt"]:.2f} pt')
    for span in spans:
        rect = fitz.Rect(span['bbox'])
        if rect.x0 < -.5 or rect.y0 < -.5 or rect.x1 > page.rect.width+.5 or rect.y1 > page.rect.height+.5:
            _fail("TEXT_OUTSIDE_CANVAS", span['text'])
        if '\ufffd' in span['text'] or '\u25a1' in span['text']:
            _fail("MISSING_GLYPH", span['text'])
    pix = page.get_pixmap(dpi=round(checks['dpi']), alpha=False)
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    stream = io.BytesIO(); im.save(stream, format='PNG', dpi=(checks['dpi'], checks['dpi']))
    payloads = {'.svg': svg, '.pdf': pdf.tobytes(garbage=4, deflate=True, no_new_id=True), '.png': stream.getvalue()}
    stem = str(spec['output_stem'])
    output_paths = {ext: _path(root, stem+ext) for ext in payloads}
    for target in output_paths.values():
        if target.exists():
            _fail("OUTPUT_EXISTS", str(target.relative_to(root)))
    outputs = []
    media = {'.svg': 'image/svg+xml', '.pdf': 'application/pdf', '.png': 'image/png'}
    for ext, data in payloads.items():
        outputs.append({'path': stem+ext, 'format': ext[1:].upper(), 'media_type': media[ext],
                        'sha256': _sha(data), 'byte_size': len(data), 'owner_run_id': spec['run_id'],
                        'run_owned': True, 'overwrite_policy': 'CREATE_NEW'})
    receipt = {'renderer_ref': RENDERER_REF, 'renderer_sha256': _sha(Path(__file__).read_bytes()), 'shell': False,
               'argv': ['python', '-m', 'research_agent_teams.tools.scientific_figure', 'render'],
               'fixed_parameters': dict(spec), 'parameters_sha256': _hash(spec),
               'source_set_sha256': _hash(spec['source_inputs']), 'output_set_sha256': _hash(outputs)}
    receipt['receipt_sha256'] = _hash(receipt)
    permission = {'status': 'OWNED', 'license_ref': 'original-scientific-illustration', 'public_release_allowed': True}
    if spec.get('artwork'):
        permission_file = stem+'-artwork-permission.json'
        permissions = {'status': 'CLEARED', 'public_release_allowed': True, 'artwork': spec['artwork'], 'basis': 'Item-level licence records; not a legal certification.'}
        pdata = _canonical(permissions)
        permission = {'status': 'CLEARED', 'license_ref': 'item-level-artwork-register', 'public_release_allowed': True,
                      'permission_receipt_ref': permission_file, 'permission_receipt_sha256': _sha(pdata)}
        ptarget = _path(root, permission_file)
        if ptarget.exists():
            _fail('OUTPUT_EXISTS', permission_file)
        output_paths['.permission'] = ptarget;payloads['.permission'] = pdata
    asset = {k: copy.deepcopy(spec[k]) for k in ['asset_id', 'label', 'caption', 'accessibility_text', 'claim_refs', 'source_inputs']}
    asset.update(semantic_type='CONCEPTUAL_SCHEMATIC', render_template='SCIENTIFIC_ILLUSTRATION',
                 outputs=outputs, permission=permission, render_receipt=receipt)
    asset['asset_record_sha256'] = _hash(asset)
    checks.update(pixels=[pix.width, pix.height], effective_dpi=pix.width/(checks['width_mm']/25.4), color_mode='RGB',
                  vector_pdf=True, editable_svg=True, automatic_checks='PASS')
    for ext, target in output_paths.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as f:
            f.write(payloads[ext])
    return {'asset': asset, 'checks': checks, 'render_environment': _environment()}


def bundle_manifest(run_id: str, manuscript_sha256: str, plan: Mapping[str, Any], rendered: list[Mapping[str, Any]]) -> dict[str, Any]:
    assets = [copy.deepcopy(r['asset']) for r in rendered]
    ids = [a['asset_id'] for a in assets];labels = [a['label'] for a in assets]
    paths = [o['path'] for a in assets for o in a['outputs']]
    if len(set(ids)) != len(ids) or len(set(labels)) != len(labels) or len(set(paths)) != len(paths):
        _fail('DUPLICATE_ASSET', 'bundle IDs, labels and paths must be unique')
    wanted = plan.get('assets', [])
    pids = [a['asset_id'] for a in wanted];plabels = [a['label'] for a in wanted]
    ppaths = [a['output_stem']+ext for a in wanted for ext in ['.svg', '.pdf', '.png']]
    if not wanted or ids != pids or labels != plabels or paths != ppaths:
        _fail('INCOMPLETE_PLAN', 'realized assets do not match the actual requested plan')
    if any(o['owner_run_id'] != run_id for a in assets for o in a['outputs']):
        _fail('OWNER_MISMATCH', run_id)
    value = {'schema_version': '2.0.0', 'run_id': run_id, 'manuscript_sha256': manuscript_sha256,
             'asset_plan_sha256': _hash(plan), 'render_environment': _environment(), 'assets': assets,
             'plan_closure': {'status': 'CLOSED', 'planned_asset_ids': pids, 'rendered_asset_ids': ids,
                              'planned_labels': plabels, 'rendered_labels': labels,
                              'planned_output_refs': ppaths, 'rendered_output_refs': paths}}
    value['manifest_sha256'] = _hash(value)
    return value


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['doctor', 'check', 'render']);p.add_argument('--run-dir');p.add_argument('--spec')
    a = p.parse_args(argv)
    try:
        if a.action == 'doctor':
            result = {'available': True, 'environment': _environment(), 'network': False, 'external_skills': False}
        else:
            if not a.run_dir or not a.spec:
                p.error('--run-dir and --spec are required')
            root = Path(a.run_dir).resolve();spec = json.loads(_path(root, a.spec).read_text(encoding='utf-8'))
            result = validate_spec(root, spec) if a.action == 'check' else render_figure(root, spec)
        print(json.dumps(result, ensure_ascii=False, indent=2));return 0
    except (ScientificFigureError, ImportError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=False));return 2


if __name__ == '__main__':
    raise SystemExit(main())
