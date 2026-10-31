"""Answering questions with Gemini + File Search, using the user's chosen params."""
from fastapi import HTTPException
from google.genai import types

from ..schemas import ChatRequest, ChatResponse, Citation
from .gemini import aio, gemini_slot
from .stores import available_models, default_model, shared_store_name, user_store_name

_MAX_CITATION_CHARS = 500


def build_generate_config(req: ChatRequest, store_names: list[str]) -> types.GenerateContentConfig:
    g, r = req.generation, req.retrieval
    tools = []
    if store_names:
        tools.append(
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=store_names,
                    top_k=r.top_k,
                    metadata_filter=(r.metadata_filter or None),
                )
            )
        )
    return types.GenerateContentConfig(
        system_instruction=g.system_instruction or None,
        temperature=g.temperature,
        top_p=g.top_p,
        top_k=g.top_k,
        max_output_tokens=g.max_output_tokens,
        tools=tools or None,
    )


def extract_citations(response: types.GenerateContentResponse, shared: str | None, mine: str | None) -> list[Citation]:
    """Grounding sources live in candidates[0].grounding_metadata.grounding_chunks."""
    if not response.candidates:
        return []
    meta = response.candidates[0].grounding_metadata
    if not meta or not meta.grounding_chunks:
        return []
    seen, out = set(), []
    for chunk in meta.grounding_chunks:
        ctx = chunk.retrieved_context
        if not ctx:
            continue
        text = (ctx.text or "").strip()
        key = (ctx.title, text[:100])
        if key in seen:
            continue
        seen.add(key)
        store = ctx.file_search_store
        source = "shared" if store and store == shared else "mine" if store and store == mine else "unknown"
        if len(text) > _MAX_CITATION_CHARS:
            text = text[:_MAX_CITATION_CHARS].rstrip() + "..."
        out.append(Citation(title=ctx.title, text=text or None, page=ctx.page_number, source=source))
    return out


async def answer(user_id: str, req: ChatRequest) -> ChatResponse:
    model = req.generation.model or await default_model()
    if model not in await available_models():
        raise HTTPException(400, f"Model '{model}' is not enabled on this server")

    shared = await shared_store_name() if req.retrieval.include_shared else None
    mine = await user_store_name(user_id) if req.retrieval.include_mine else None
    stores = [s for s in (shared, mine) if s]

    contents = [
        types.Content(role=t.role, parts=[types.Part(text=t.text)]) for t in req.history
    ] + [types.Content(role="user", parts=[types.Part(text=req.question)])]

    async with gemini_slot():
        response = await aio.models.generate_content(
            model=model, contents=contents, config=build_generate_config(req, stores)
        )

    text = response.text
    if not text:
        reason = response.candidates[0].finish_reason if response.candidates else None
        text = f"(No answer returned{f': {reason}' if reason else ''}.)"
    return ChatResponse(
        answer=text,
        citations=extract_citations(response, shared, mine),
        model=model,
        searched_stores=len(stores),
    )
