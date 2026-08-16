"""The two doors between pandas values and the rest of the app.

Producer outputs are CSVs, so a blank cell arrives as NaN -- a float that is
*truthy*. Every `value or default` guard in this codebase therefore passes it
straight through, and the NaN sits in a text field until something compares it
to a string, at which point a request 500s a long way from the blank cell that
caused it. That is the failure this module exists to make impossible:

- `records()` is how frame rows become dicts. NaN turns into None at the
  boundary, so the ordinary `or` guards downstream start working. Use it
  instead of `DataFrame.to_dict("records")` -- there is no reason to reach for
  the raw call, and using it everywhere is what makes the guarantee worth
  anything.
- `sort_key()` is how values are compared when the rows being sorted come from
  more than one file or producer. Ingress cleaning cannot help there: two
  producers can legitimately write the same column as text and as a number,
  and sorting is where that difference becomes an outage rather than a
  cosmetic inconsistency.

Neither is clever. The point is that there is one door of each kind.
"""
import math

# Sorting rank by kind, so keys of different kinds are still comparable:
# missing values first, then numbers, then text.
_MISSING, _NUMBER, _TEXT = 0, 1, 2


def records(frame):
    """Frame rows as plain dicts, with pandas' NaN already turned into None."""
    if frame is None or frame.empty:
        return []
    present = frame.notna()
    if present.to_numpy().all():
        # Nothing to replace. Worth checking: the object copy below costs real
        # time on the price book's frames, and most frames have no gaps at all.
        return frame.to_dict("records")
    return frame.astype(object).where(present, None).to_dict("records")


def sort_key(value):
    """A stand-in for `value` that can be compared with any other sort key.

    Returns a fixed-shape tuple, so `sort`/`max` never compare a float with a
    string no matter what a producer wrote in the column.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return (_MISSING, 0.0, "")
    if isinstance(value, bool):
        return (_NUMBER, float(value), "")
    if isinstance(value, (int, float)):
        return (_NUMBER, float(value), "")
    return (_TEXT, 0.0, str(value))
