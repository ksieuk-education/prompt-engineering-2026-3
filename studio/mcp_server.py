"""Отдельный MCP-сервер. Запуск: python -m studio.mcp_server (stdio)."""

from mcp.server.fastmcp import FastMCP

from . import audio_search, clock_tools, recordings, repeats, semantic, transcript

mcp = FastMCP("Архивные часы", log_level="WARNING")


@mcp.tool()
def locate_marker(
    case_id: str, marker: str = "", basis: clock_tools.ClockBasis = "air"
) -> dict:
    """Прочитать отметку на копии (tape) или восстановить эфирное время (air) по зафиксированным опорам."""
    return clock_tools.locate_marker(case_id, marker, basis)


@mcp.tool()
def tape_span(case_id: str, first: str, second: str) -> dict:
    """Измерить расстояние между любыми двумя метками копии по счетчику ленты."""
    return clock_tools.tape_span(case_id, first, second)


@mcp.tool()
def compare_span(case_id: str) -> dict:
    """Сравнить интервал между двумя общими метками в эфире и на копии."""
    return clock_tools.compare_span(case_id)


@mcp.tool()
def match_sound(
    case_id: str, start_seconds: float, scope: audio_search.Scope = "archive"
) -> dict:
    """Найти в WAV катушки или архива другие появления образца с указанной секунды."""
    return audio_search.match_sound(case_id, start_seconds, scope)


@mcp.tool()
def compare_repeat_clocks(
    case_id: str,
    start_seconds: float,
    scope: audio_search.Scope = "archive",
    candidate_case: str = "",
    candidate_second: float | None = None,
    other_tape: bool = False,
) -> dict:
    """Заново найти звуковой повтор и сверить счетчик каждой копии с документами ее собственного дела."""
    return repeats.compare_repeat_clocks(
        case_id, start_seconds, scope, candidate_case, candidate_second, other_tape
    )


@mcp.tool()
def compare_public(
    candidate: recordings.FieldTarget, at: float, scan_speed: bool = False
) -> dict:
    """Сравнить указанный отрезок короткой записи NASA с длинной версией или контрольной репликой."""
    return recordings.compare_public(candidate, at, scan_speed=scan_speed)


@mcp.tool()
def search_transcript(
    query: str,
    speaker: str = "",
    exact: bool = False,
    page: int | None = None,
    clock: str = "",
) -> dict:
    """Найти строки по английской фразе или времени миссии. clock принимает ЧЧЧ:ММ:СС или интервал включительно."""
    return transcript.search_transcript(
        query, speaker=speaker, exact=exact, page=page, clock=clock
    )


@mcp.tool()
def rank_transcript(question: str, queries: list[str], page: int | None = None) -> dict:
    """Найти возможные строки по русскому описанию и английским словам через FTS5 и локальные эмбеддинги."""
    return semantic.ranked_candidates(question, queries, page=page)


@mcp.tool()
def read_transcript(line_id: int, offset: int = 0) -> dict:
    """Открыть найденную, предыдущую или следующую размеченную реплику стенограммы Apollo 11."""
    if offset not in {-1, 0, 1}:
        raise ValueError("Можно перейти только к соседней реплике.")
    return {"line": transcript.adjacent(line_id, offset)}


@mcp.tool()
def read_transcript_page(number: int) -> dict:
    """Проверить номер печатной страницы стенограммы, ее источник и наличие реплик."""
    return transcript.page_info(number)


if __name__ == "__main__":
    mcp.run(transport="stdio")
