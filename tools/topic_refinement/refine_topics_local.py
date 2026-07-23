#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.topic_detection.refinement import (  # noqa: E402
    RESULT_SCHEMA_VERSION,
    build_refinement_prompt,
    topic_refinement_system_prompt,
    validate_refinement,
)
from app.domains.topic_detection.refinement_io import (  # noqa: E402
    JOB_SCHEMA_VERSION,
    RESULT_RECORD_TYPE,
    load_jsonl,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refine exported Friend Hub topic jobs with a local LLM. Export files contain private chat excerpts.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Input topic refinement jobs JSONL")
    parser.add_argument("--manifest", required=True, type=Path, help="Export manifest JSON")
    parser.add_argument("--output", required=True, type=Path, help="Output topic refinement results JSONL")
    parser.add_argument("--report", type=Path, default=None, help="Optional Markdown review report")
    parser.add_argument("--provider", choices=["ollama", "openai-compatible"], default="ollama")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--limit-topics", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print a summary without writing output/report files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output/report files")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--include-excerpts-in-report", action="store_true")
    args = parser.parse_args()

    payload = refine_file(
        input_path=args.input,
        manifest_path=args.manifest,
        output_path=args.output,
        report_path=args.report,
        provider=args.provider,
        base_url=args.base_url,
        model=args.model,
        limit_topics=args.limit_topics,
        dry_run=args.dry_run,
        force=args.force,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        max_retries=args.max_retries,
        timeout=args.timeout,
        include_excerpts_in_report=args.include_excerpts_in_report,
    )
    print(json.dumps(payload, sort_keys=True))


def refine_file(
    *,
    input_path: Path,
    manifest_path: Path,
    output_path: Path,
    report_path: Path | None,
    provider: str,
    base_url: str,
    model: str,
    limit_topics: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    temperature: float = 0.0,
    max_tokens: int = 512,
    max_retries: int = 2,
    timeout: float = 120.0,
    include_excerpts_in_report: bool = False,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = [
        job for job in load_jsonl(input_path)
        if job.get("schema_version") == JOB_SCHEMA_VERSION and job.get("record_type") == "topic_job"
    ]
    if limit_topics is not None:
        jobs = jobs[:max(1, limit_topics)]
    if not dry_run and output_path.exists() and not force:
        raise FileExistsError(f"{output_path} already exists; pass --force to overwrite")
    if not dry_run and report_path and report_path.exists() and not force:
        raise FileExistsError(f"{report_path} already exists; pass --force to overwrite")

    results = []
    report_rows = []
    output_handle = None
    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_handle = output_path.open("w", encoding="utf-8")
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        for index, job in enumerate(jobs, start=1):
            print(f"refining topic {index}/{len(jobs)} {job.get('topic_id')}", file=sys.stderr, flush=True)
            result = refine_job(
                job=job,
                manifest=manifest,
                provider=provider,
                base_url=base_url,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries=max_retries,
                timeout=timeout,
            )
            results.append(result)
            report_rows.append((job, result))
            if output_handle is not None:
                output_handle.write(json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n")
                output_handle.flush()
            if not dry_run and report_path:
                report_path.write_text(
                    build_report(report_rows, include_excerpts=include_excerpts_in_report),
                    encoding="utf-8",
                )
    finally:
        if output_handle is not None:
            output_handle.close()

    refined = sum(1 for result in results if result.get("status") == "refined")
    failed = sum(1 for result in results if result.get("status") == "failed")
    return {
        "status": "ok",
        "dry_run": dry_run,
        "input": str(input_path),
        "manifest": str(manifest_path),
        "output": None if dry_run else str(output_path),
        "report": None if dry_run or report_path is None else str(report_path),
        "provider": provider,
        "model": model,
        "jobs_read": len(jobs),
        "refined": refined,
        "failed": failed,
        "privacy_note": "Input/output files contain private chat excerpts or derived summaries. Store securely and delete after import.",
    }


def refine_job(
    *,
    job: dict,
    manifest: dict,
    provider: str,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int = 512,
    max_retries: int,
    timeout: float,
) -> dict:
    base = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "record_type": RESULT_RECORD_TYPE,
        "export_id": job.get("export_id") or manifest.get("export_id"),
        "topic_id": job.get("topic_id"),
        "room_id": job.get("room_id"),
        "topic_date": job.get("topic_date"),
        "source_hash": job.get("source_hash"),
    }
    try:
        prompt = build_refinement_prompt(
            raw_label=job.get("raw_label"),
            confidence=job.get("confidence"),
            started_at=job.get("started_at"),
            ended_at=job.get("ended_at"),
            batch_count=len(job.get("segments") or []),
            segments=job.get("segments") or [],
            participants=job.get("participants") or [],
            max_segments=int((job.get("limits") or {}).get("max_segments") or manifest.get("max_segments") or 8),
            max_excerpt_chars=int((job.get("limits") or {}).get("max_excerpt_chars") or manifest.get("max_excerpt_chars") or 500),
        )
        raw = call_local_model(
            provider=provider,
            base_url=base_url,
            model=model,
            system_prompt=topic_refinement_system_prompt(),
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout=timeout,
        )
        proposal = validate_refinement(raw)
        reasoning_note = _clean_reasoning_note(raw.get("reasoning_note"))
    except Exception as exc:
        return {
            **base,
            "status": "failed",
            "error": str(exc),
        }
    result = {
        **base,
        "status": "refined",
        "refined_label": proposal.title,
        "summary": proposal.summary,
        "tags": proposal.tags,
        "topic_type": proposal.topic_type,
        "confidence": proposal.confidence,
        "refinement_model": f"local:{model}",
        "refined_at": datetime.now(timezone.utc).isoformat(),
    }
    if reasoning_note:
        result["reasoning_note"] = reasoning_note
    return result


def call_local_model(
    *,
    provider: str,
    base_url: str,
    model: str,
    system_prompt: str,
    prompt: str,
    temperature: float,
    max_tokens: int = 512,
    max_retries: int,
    timeout: float,
) -> dict:
    last_error = None
    for attempt in range(max(0, max_retries) + 1):
        try:
            if provider == "ollama":
                response = _post_json(
                    f"{base_url.rstrip('/')}/api/generate",
                    {
                        "model": model,
                        "system": system_prompt,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": temperature, "num_predict": max(64, int(max_tokens))},
                    },
                    timeout=timeout,
                )
                return _extract_json(response.get("response", ""))
            if provider == "openai-compatible":
                response = _post_json(
                    f"{base_url.rstrip('/')}/chat/completions",
                    {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": temperature,
                        "max_tokens": max(64, int(max_tokens)),
                    },
                    timeout=timeout,
                )
                return _extract_json(response["choices"][0]["message"]["content"])
            raise ValueError(f"Unsupported provider {provider!r}")
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 5))
    raise RuntimeError(f"local model call failed: {last_error}") from last_error


def build_report(rows: list[tuple[dict, dict]], *, include_excerpts: bool = False) -> str:
    lines = [
        "# Topic Refinement Review",
        "",
        "This report intentionally omits full excerpts by default because the source files contain private chat data.",
        "",
    ]
    for job, result in rows:
        lines.extend([
            f"## {job.get('topic_id')}",
            "",
            f"- Raw label: {job.get('raw_label')}",
            f"- Refined label: {result.get('refined_label') or result.get('error')}",
            f"- Summary: {result.get('summary', '')}",
            f"- Tags: {', '.join(result.get('tags') or [])}",
            f"- Topic type: {result.get('topic_type', '')}",
            f"- Confidence: {result.get('confidence', '')}",
            f"- Participants: {_participant_names(job)}",
            f"- Segment count: {len(job.get('segments') or [])}",
            f"- Time range: {job.get('started_at')} to {job.get('ended_at')}",
        ])
        if result.get("reasoning_note"):
            lines.append(f"- Reasoning note: {result['reasoning_note']}")
        if include_excerpts and job.get("segments"):
            excerpt = (job["segments"][0].get("excerpt") or "")[:120]
            lines.append(f"- First excerpt preview: {excerpt}")
        lines.append("")
    return "\n".join(lines)


def _participant_names(job: dict) -> str:
    names = [
        str(participant.get("canonical_name") or "").strip()
        for participant in (job.get("participants") or [])
        if str(participant.get("canonical_name") or "").strip()
    ]
    return ", ".join(names[:12]) if names else "unknown"


def _clean_reasoning_note(value) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:240] or None


def _post_json(url: str, payload: dict, *, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _extract_json(text: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        raise ValueError("No JSON object found in model response")
    return json.loads(match.group())


if __name__ == "__main__":
    main()
