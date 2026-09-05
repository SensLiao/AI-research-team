"""Journal choice and a small automatic figure-plan handoff before final rendering.

The conversational host asks the question; this module records its real answer
or the user-authorized no-preference recommendation. It never invents consent,
chooses a journal from a hardcoded domain, downloads templates, or submits papers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from research_agent_teams.tools.scientific_figure import (
    ScientificFigureError, RENDERER_REF, _canonical, _hash, _path, _sha, render_figure, bundle_manifest, validate_spec,
)


def journal_question(recommended_journal: str) -> str:
    return f"这次最终稿准备投什么期刊？如果暂未指定，建议按 {recommended_journal} 的要求完成图表和排版。"


def choose_journal(*, render_id: str, profile: Mapping[str, Any], answer: str | None,
                   question_asked: bool, recommendation_reason: str = "") -> dict[str, Any]:
    """An empty preference uses the supplied, evidence-grounded recommendation."""
    if not question_asked:
        raise ScientificFigureError('JOURNAL_QUESTION_REQUIRED: '+journal_question(str(profile.get('name','目标期刊'))))
    if not profile.get('journal_id') or not profile.get('official_rule_sources'):
        raise ScientificFigureError('JOURNAL_PROFILE_REQUIRED: dated official rules must accompany the choice')
    aliases = {str(v).strip().casefold() for v in [profile['journal_id'],profile.get('name',''),*profile.get('aliases',[])]}
    if answer and answer.strip().casefold() not in aliases:
        raise ScientificFigureError('DIFFERENT_JOURNAL_PROFILE_REQUIRED: do not substitute a default for the requested journal')
    if not answer and not recommendation_reason.strip():
        raise ScientificFigureError('RECOMMENDATION_REASON_REQUIRED: use the manuscript topic, article type and official scope')
    return {'version':'journal-choice/v1','render_id':render_id,'question_asked':True,
            'question':journal_question(str(profile['name'])),'answer':answer,
            'journal_id':profile['journal_id'],'selection':'USER_CONFIRMED' if answer else 'RECOMMENDED_NO_PREFERENCE',
            'recommendation_reason':recommendation_reason if not answer else '',
            'profile_sha256':_hash(profile),'rule_verification':profile.get('verification_status','NOT_RECORDED')}


def validate_journal_choice(choice: Mapping[str, Any], profile: Mapping[str, Any], expected_journal: str | None = None) -> None:
    if choice.get('question_asked') is not True or choice.get('selection') not in {'USER_CONFIRMED','RECOMMENDED_NO_PREFERENCE'}:
        raise ScientificFigureError('JOURNAL_QUESTION_REQUIRED: ask once before this final delivery, not on every repair retry')
    if choice.get('profile_sha256') != _hash(profile) or choice.get('journal_id') != profile.get('journal_id'):
        raise ScientificFigureError('JOURNAL_PROFILE_DRIFT: refresh the choice after changing the target or rules')
    if choice.get('selection') == 'RECOMMENDED_NO_PREFERENCE' and not choice.get('recommendation_reason'):
        raise ScientificFigureError('RECOMMENDATION_REASON_REQUIRED')
    aliases = {str(v).casefold() for v in [profile.get('journal_id',''),profile.get('name',''),*profile.get('aliases',[])]}
    if expected_journal and expected_journal.casefold() not in aliases:
        raise ScientificFigureError('FROZEN_JOURNAL_MISMATCH: a different journal requires a new manuscript snapshot')


def prepare_figure_plan(run_dir: str | Path, plan_ref: str, *, manuscript_sha256: str,
                        expected_journal: str | None = None) -> dict[str, Any]:
    """Render specified SVGs automatically, or reuse unchanged, hash-verified outputs."""
    root=Path(run_dir).resolve()
    plan=json.loads(_path(root,plan_ref).read_text(encoding='utf-8'))
    profile=json.loads(_path(root,plan['journal_profile_ref']).read_text(encoding='utf-8'))
    choice=json.loads(_path(root,plan['journal_choice_ref']).read_text(encoding='utf-8'))
    validate_journal_choice(choice,profile,expected_journal)
    specs=[json.loads(_path(root,ref).read_text(encoding='utf-8')) for ref in plan['figure_specs']]
    if not specs:
        raise ScientificFigureError('EMPTY_FIGURE_PLAN')
    for spec in specs:
        validate_spec(root,spec)
        if not str(spec['output_stem']).startswith('evidence/ANALYZE/'):
            raise ScientificFigureError('FIGURE_OUTPUT_STAGE: automatic team outputs belong under evidence/ANALYZE/')
        if spec.get('journal','').casefold() != str(choice['journal_id']).casefold():
            raise ScientificFigureError('FIGURE_JOURNAL_MISMATCH')
        targets=profile.get('internal_targets',{})
        if spec.get('dpi',600)<targets.get('raster_dpi',300) or spec.get('min_font_pt',8)<targets.get('min_label_font_pt',6):
            raise ScientificFigureError('FIGURE_PROFILE_MISMATCH: keep the selected profile or explicitly revise it')
        if spec['width_mm']>plan.get('available_figure_width_mm',250):
            raise ScientificFigureError('FIGURE_EXCEEDS_MANUSCRIPT_WIDTH')
    target=_path(root,plan['manifest_ref'])
    plan_key=_hash({'plan':plan,'specs':specs,'choice':choice,'manuscript':manuscript_sha256})
    stamp=target.with_suffix('.cache.json')
    if target.exists():
        if not stamp.is_file():raise ScientificFigureError('EXISTING_MANIFEST_WITHOUT_CACHE_RECORD')
        cache=json.loads(stamp.read_text(encoding='utf-8'));manifest=json.loads(target.read_text(encoding='utf-8'))
        if cache.get('input_key')!=plan_key or cache.get('manifest_sha256')!=_sha(target.read_bytes()):
            raise ScientificFigureError('FIGURE_CACHE_STALE: use a new revision output path')
        for asset in manifest['assets']:
            if asset['render_receipt']['renderer_ref'] != RENDERER_REF:
                raise ScientificFigureError('FIGURE_RENDERER_CHANGED')
            source=Path(__file__).with_name('scientific_figure.py')
            if _sha(source.read_bytes())!=asset['render_receipt']['renderer_sha256']:
                raise ScientificFigureError('FIGURE_RENDERER_CHANGED: use a new revision output path')
            for out in asset['outputs']:
                if _sha(_path(root,out['path']).read_bytes())!=out['sha256']:raise ScientificFigureError('FIGURE_OUTPUT_DRIFT')
            permission=asset.get('permission',{})
            if permission.get('permission_receipt_ref'):
                if _sha(_path(root,permission['permission_receipt_ref']).read_bytes())!=permission.get('permission_receipt_sha256'):
                    raise ScientificFigureError('FIGURE_PERMISSION_DRIFT')
        return {'manifest':manifest,'reused':True,'figure_count':len(specs),'journal_choice':choice}
    requested={'assets':[{'asset_id':s['asset_id'],'label':s['label'],'output_stem':s['output_stem']} for s in specs]}
    realized=[render_figure(root,s) for s in specs]
    manifest=bundle_manifest(specs[0]['run_id'],manuscript_sha256,requested,realized)
    from research_agent_teams.tools.validate_artifact import validate_payload
    errors=validate_payload('manuscript_asset_manifest',manifest)
    if errors:raise ScientificFigureError('MANIFEST_SCHEMA: '+'; '.join(errors[:3]))
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:f.write(_canonical(manifest))
    with stamp.open('xb') as f:f.write(_canonical({'input_key':plan_key,'manifest_sha256':_sha(target.read_bytes()),'checks':[r['checks'] for r in realized]}))
    return {'manifest':manifest,'reused':False,'figure_count':len(specs),'journal_choice':choice}


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['question','choose','figures'])
    p.add_argument('--run-dir',required=True);p.add_argument('--profile');p.add_argument('--answer');p.add_argument('--asked',action='store_true')
    p.add_argument('--reason',default='');p.add_argument('--render-id',default='final-delivery');p.add_argument('--output');p.add_argument('--plan');p.add_argument('--manuscript-sha256')
    a=p.parse_args(argv);root=Path(a.run_dir).resolve()
    try:
        if a.action=='figures':result=prepare_figure_plan(root,a.plan,manuscript_sha256=a.manuscript_sha256)
        else:
            profile=json.loads(_path(root,a.profile).read_text(encoding='utf-8'))
            result={'question':journal_question(profile['name'])} if a.action=='question' else choose_journal(render_id=a.render_id,profile=profile,answer=a.answer,question_asked=a.asked,recommendation_reason=a.reason)
        if a.output:
            path=_path(root,a.output);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as f:f.write(_canonical(result))
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ScientificFigureError,OSError,KeyError,TypeError,ValueError) as exc:
        print(json.dumps({'status':'NEEDS_ATTENTION','error':str(exc)},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
