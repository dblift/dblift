"""MySQL words that may sit between a DML verb and its target table."""

import re
from typing import Dict

# MySQL words valid after each verb, and Oracle optimizer hints, before the target.
# A word that continues an identifier (``quick.t``, ``ignore$x``) or is followed by
# the next clause keyword is the table itself, not a modifier.
MYSQL_DML_MODIFIER_WORDS: Dict[str, str] = {
    "UPDATE": "LOW_PRIORITY|IGNORE",
    "DELETE": "LOW_PRIORITY|QUICK|IGNORE",
    "INSERT": "LOW_PRIORITY|HIGH_PRIORITY|DELAYED|IGNORE",
    "REPLACE": "LOW_PRIORITY|DELAYED",
}
MYSQL_DML_MODIFIER: Dict[str, "re.Pattern[str]"] = {
    verb: re.compile(
        rf"\s*(?:/\*.*?\*/|(?:{words})(?![\w$#])(?!\s*(?:\.|SET\b|WHERE\b|VALUES\b|\(|;|$)))",
        re.IGNORECASE | re.DOTALL,
    )
    for verb, words in MYSQL_DML_MODIFIER_WORDS.items()
}
