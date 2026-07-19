"""Provider runtime routes: model policy, ASR/OCR provider runtime, production extractor."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from model_policy import load_model_policy
from production_extractor import (
    ProductionExtractorError,
    run_production_extractor,
)
from provider_runtime import (
    ProviderRuntimeError,
    analyze_frame,
    runtime_status as provider_runtime_status,
    transcribe_audio,
)
from runtime_usage import append_runtime_usage_event
from schemas import ProductionExtractorReq, ProviderAsrReq, ProviderOcrReq

router = APIRouter()


@router.get("/api/model-policy")
def model_policy():
    return load_model_policy()


@router.get("/api/provider-runtime/status")
def provider_runtime_status_api():
    return provider_runtime_status()


@router.post("/api/provider-runtime/asr")
def provider_runtime_asr(req: ProviderAsrReq):
    try:
        result = transcribe_audio(
            filename=req.filename,
            media_base64=req.media_base64,
            media_mime=req.media_mime,
            task=req.task,
            mode=req.mode,
            language=req.language,
            prompt=req.prompt,
        )
        if result.get("execution_mode") == "real":
            append_runtime_usage_event(
                task=result.get("task", req.task),
                provider=result.get("provider", "openai"),
                model=result.get("model", ""),
                mode=result.get("execution_mode", req.mode),
                endpoint="/api/provider-runtime/asr",
                usage=result.get("usage", {"confidence": "not_available"}),
                provider_call_count=int(result.get("provider_call_count") or 0),
                raw_evidence_ref="runtime:provider-runtime/asr:response_metadata",
                decision_scope="ASR provider usage accounting only; no media or transcript text stored",
            )
        return result
    except ProviderRuntimeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/api/provider-runtime/ocr")
def provider_runtime_ocr(req: ProviderOcrReq):
    try:
        result = analyze_frame(
            filename=req.filename,
            image_base64=req.image_base64,
            image_mime=req.image_mime,
            mode=req.mode,
            prompt=req.prompt,
        )
        if result.get("execution_mode") == "real":
            append_runtime_usage_event(
                task=result.get("task", "ocr_visual"),
                provider=result.get("provider", "openai"),
                model=result.get("model", ""),
                mode=result.get("execution_mode", req.mode),
                endpoint="/api/provider-runtime/ocr",
                usage=result.get("usage", {"confidence": "not_available"}),
                provider_call_count=int(result.get("provider_call_count") or 0),
                raw_evidence_ref="runtime:provider-runtime/ocr:response_metadata",
                decision_scope="OCR provider usage accounting only; no image or extracted text stored",
            )
        return result
    except ProviderRuntimeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/api/production-extractor")
def production_extractor_api(req: ProductionExtractorReq):
    try:
        result = run_production_extractor(
            url=req.url,
            mode=req.mode,
            sample_count=req.sample_count,
            max_provider_calls=req.max_provider_calls,
            user_authorized_media=req.user_authorized_media,
            allow_provider_ocr=req.allow_provider_ocr,
            confirm_report_only=req.confirm_report_only,
            prompt=req.prompt,
        )
        if result.get("execution_mode") == "real":
            append_runtime_usage_event(
                task=result.get("provider_task", "ocr_visual"),
                provider=result.get("provider", "openai"),
                model=result.get("provider_model", ""),
                mode=result.get("execution_mode", req.mode),
                endpoint="/api/production-extractor",
                usage={
                    "quality": result.get("quality", {}),
                    "frame_count": result.get("sampled_frame_count", 0),
                    "provider_evidence_count": result.get("provider_evidence_count", 0),
                },
                provider_call_count=int(result.get("provider_call_count") or 0),
                raw_evidence_ref="runtime:production-extractor:report-only",
                decision_scope="production extractor OCR evidence accounting only; no raw media/source note stored",
            )
        return result
    except ProductionExtractorError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except ProviderRuntimeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
