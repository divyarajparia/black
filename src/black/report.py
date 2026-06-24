"""
Summarize Black runs to users.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import IO, Any

from black.output import err, out, style_output


class Changed(Enum):
    NO = 0
    CACHED = 1
    YES = 2


class NothingChanged(UserWarning):
    """Raised when reformatted code is the same as source."""


@dataclass
class Report:
    """Provides a reformatting counter. Can be rendered with `str(report)`."""

    check: bool = False
    diff: bool = False
    quiet: bool = False
    verbose: bool = False
    change_count: int = 0
    same_count: int = 0
    failure_count: int = 0
    # When set, per-file results are accumulated and a JSON report is written here.
    json_report_file: IO[str] | None = field(default=None, repr=False, compare=False)
    _file_results: list[dict[str, Any]] = field(
        default_factory=list, init=False, repr=False, compare=False
    )

    def done(self, src: Path, changed: Changed) -> None:
        """Increment the counter for successful reformatting. Write out a message."""
        if changed is Changed.YES:
            reformatted = "would reformat" if self.check or self.diff else "reformatted"
            if self.verbose or not self.quiet:
                out(f"{reformatted} {src}")
            self.change_count += 1
            status = "reformatted"
        else:
            if self.verbose:
                if changed is Changed.NO:
                    msg = f"{src} already well formatted, good job."
                else:
                    msg = f"{src} wasn't modified on disk since last run."
                out(msg, bold=False)
            self.same_count += 1
            status = "unchanged" if changed is Changed.NO else "cached"

        if self.json_report_file is not None:
            self._file_results.append({"src": str(src), "status": status})

    def failed(self, src: Path, message: str) -> None:
        """Increment the counter for failed reformatting. Write out a message."""
        err(f"error: cannot format {src}: {message}")
        self.failure_count += 1
        if self.json_report_file is not None:
            self._file_results.append(
                {"src": str(src), "status": "failed", "error": message}
            )

    def write_json_report(self) -> None:
        """Serialize results to JSON and write them to ``json_report_file``.

        The report has the following structure::

            {
                "summary": {
                    "reformatted": <int>,
                    "unchanged": <int>,
                    "failed": <int>
                },
                "files": [
                    {"src": "<path>", "status": "reformatted" | "unchanged" | "cached" | "failed", "error": "<msg>"},
                    ...
                ]
            }

        Call this method after all files have been processed.
        """
        if self.json_report_file is None:
            return
        payload: dict[str, Any] = {
            "summary": {
                "reformatted": self.change_count,
                "unchanged": self.same_count,
                "failed": self.failure_count,
            },
            "files": self._file_results,
        }
        json.dump(payload, self.json_report_file, indent=2)
        self.json_report_file.write("\n")

    def path_ignored(self, path: Path, message: str) -> None:
        if self.verbose:
            out(f"{path} ignored: {message}", bold=False)

    @property
    def return_code(self) -> int:
        """Return the exit code that the app should use.

        This considers the current state of changed files and failures:
        - if there were any failures, return 123;
        - if any files were changed and --check is being used, return 1;
        - otherwise return 0.
        """
        # According to http://tldp.org/LDP/abs/html/exitcodes.html starting with
        # 126 we have special return codes reserved by the shell.
        if self.failure_count:
            return 123

        elif self.change_count and self.check:
            return 1

        return 0

    def __str__(self) -> str:
        """Render a color report of the current state.

        Use `click.unstyle` to remove colors.
        """
        if self.check or self.diff:
            reformatted = "would be reformatted"
            unchanged = "would be left unchanged"
            failed = "would fail to reformat"
        else:
            reformatted = "reformatted"
            unchanged = "left unchanged"
            failed = "failed to reformat"
        report = []
        if self.change_count:
            s = "s" if self.change_count > 1 else ""
            report.append(
                style_output(f"{self.change_count} file{s} ", bold=True, fg="blue")
                + style_output(f"{reformatted}", bold=True)
            )

        if self.same_count:
            s = "s" if self.same_count > 1 else ""
            report.append(
                style_output(f"{self.same_count} file{s} ", fg="blue") + unchanged
            )
        if self.failure_count:
            s = "s" if self.failure_count > 1 else ""
            report.append(
                style_output(f"{self.failure_count} file{s} {failed}", fg="red")
            )
        return ", ".join(report) + "."
