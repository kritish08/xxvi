from xxvi.content.schema import RunConfig


def score_for(config: RunConfig, cleared_segments: list[int]) -> int | None:
    """Total points for the segments cleared so far, or None if scoring is off.

    Pure: no I/O, no session, no run row. The caller passes
    `Run.cleared_segments` straight in. Returning None rather than 0 when
    nobody configured points is what lets the UI distinguish "this run has no
    score" from "this run has scored nothing yet" -- rendering a bold 0 to
    someone who never opted into scoring would be a worse bug than showing
    no score at all.
    """
    if all(q.points is None for q in config.questions):
        return None
    total = 0
    for segment in cleared_segments:
        # Segments are 1-indexed and validated to cover 1..total_segments
        # exactly once, so this index is always in range for a loaded config.
        question = config.questions[segment - 1]
        total += question.points or 0
    return total
