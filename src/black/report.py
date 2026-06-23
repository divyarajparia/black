"""
Summarize Black runs to users.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from black.output import err, out, style_output


class Changed(Enum):
    NO = 0
    CACHED = 1
    YES = 2


class NothingChanged(UserWarning):
    """Raised when reformatted code is the same as source."""


class FileStats(NamedTuple):
    """Line-level statistics for a single reformatted file."""

    src_lines: int
    dst_lines: int

    @property
    def lines_changed(self) -> int:
        return abs(self.dst_lines - self.src_lines)

    @property
    def net_change(self) -> int:
        """Positive means lines were added, negative means lines were removed."""
        return self.dst_lines - self.src_lines


@dataclass
class Report:
    """Provides a reformatting counter. Can be rendered with `str(report)`."""

    check: bool = False
    diff: bool = False
    quiet: bool = False
    verbose: bool = False
    statistics: bool = False
    change_count: int = 0
    same_count: int = 0
    failure_count: int = 0
    _file_stats: dict[Path, FileStats] = field(default_factory=dict)

    def done(self, src: Path, changed: Changed) -> None:
        """Increment the counter for successful reformatting. Write out a message."""
        if changed is Changed.YES:
            reformatted = "would reformat" if self.check or self.diff else "reformatted"
            if self.verbose or not self.quiet:
                out(f"{reformatted} {src}")
            self.change_count += 1
        else:
            if self.verbose:
                if changed is Changed.NO:
                    msg = f"{src} already well formatted, good job."
                else:
                    msg = f"{src} wasn't modified on disk since last run."
                out(msg, bold=False)
            self.same_count += 1

    def done_with_stats(
        self,
        src: Path,
        changed: Changed,
        src_lines: int,
        dst_lines: int,
    ) -> None:
        """Like :meth:`done`, but also records per-file line statistics.

        This is used when ``--statistics`` is active so that a detailed
        breakdown of line-level changes can be shown at the end of the run.
        """
        self.done(src, changed)
        if changed is Changed.YES:
            self._file_stats[src] = FileStats(src_lines=src_lines, dst_lines=dst_lines)

    def failed(self, src: Path, message: str) -> None:
        """Increment the counter for failed reformatting. Write out a message."""
        err(f"error: cannot format {src}: {message}")
        self.failure_count += 1

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

    def print_statistics(self) -> None:
        """Print a per-file line-change statistics table to stderr.

        Only files that were actually reformatted (i.e. had changes) are
        included.  Files are sorted by the absolute number of lines changed
        (descending) so the most-impacted files appear first.

        Example output::

            ── Black statistics ──────────────────────────────────────
            File                            Before  After   Δ lines
            ─────────────────────────────────────────────────────────
            src/black/__init__.py             1 823  1 810      -13
            src/black/linegen.py                942    955      +13
            ─────────────────────────────────────────────────────────
            Total (2 files)                   2 765  2 765        0
        """
        if not self._file_stats:
            return

        sorted_files = sorted(
            self._file_stats.items(),
            key=lambda kv: kv[1].lines_changed,
            reverse=True,
        )

        # Measure column widths dynamically so the table looks good regardless
        # of path lengths.
        file_col_width = max(
            len("File"),
            max(len(str(p)) for p in self._file_stats),
        )
        before_col_width = max(
            len("Before"),
            max(len(f"{s.src_lines:,}") for s in self._file_stats.values()),
        )
        after_col_width = max(
            len("After"),
            max(len(f"{s.dst_lines:,}") for s in self._file_stats.values()),
        )

        total_src = sum(s.src_lines for s in self._file_stats.values())
        total_dst = sum(s.dst_lines for s in self._file_stats.values())
        total_net = total_dst - total_src
        total_label = f"Total ({len(self._file_stats)} file{'s' if len(self._file_stats) != 1 else ''})"

        delta_col_width = max(
            len("Δ lines"),
            max(len(_format_net(s.net_change)) for s in self._file_stats.values()),
            len(_format_net(total_net)),
            len(total_label),
        )

        sep_width = file_col_width + before_col_width + after_col_width + delta_col_width + 9
        separator = "─" * sep_width

        header_title = " Black statistics "
        title_line = style_output(
            f"── {header_title}" + "─" * (sep_width - len(f"── {header_title}")),
            bold=True,
        )
        out(title_line, err=True)

        header = (
            style_output(f"{'File':<{file_col_width}}", bold=True)
            + "  "
            + style_output(f"{'Before':>{before_col_width}}", bold=True)
            + "  "
            + style_output(f"{'After':>{after_col_width}}", bold=True)
            + "  "
            + style_output(f"{'Δ lines':>{delta_col_width}}", bold=True)
        )
        out(header, err=True)
        out(style_output(separator, bold=False), err=True)

        for path, stats in sorted_files:
            net_str = _format_net(stats.net_change)
            net_colored = style_output(
                f"{net_str:>{delta_col_width}}",
                fg="green" if stats.net_change < 0 else "red" if stats.net_change > 0 else None,
            )
            line = (
                f"{str(path):<{file_col_width}}"
                + "  "
                + f"{stats.src_lines:>{before_col_width},}"
                + "  "
                + f"{stats.dst_lines:>{after_col_width},}"
                + "  "
                + net_colored
            )
            out(line, err=True)

        out(style_output(separator, bold=False), err=True)

        total_net_str = _format_net(total_net)
        total_net_colored = style_output(
            f"{total_net_str:>{delta_col_width}}",
            fg="green" if total_net < 0 else "red" if total_net > 0 else None,
        )
        total_line = (
            style_output(f"{total_label:<{file_col_width}}", bold=True)
            + "  "
            + style_output(f"{total_src:>{before_col_width},}", bold=True)
            + "  "
            + style_output(f"{total_dst:>{after_col_width},}", bold=True)
            + "  "
            + total_net_colored
        )
        out(total_line, err=True)

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


def _format_net(n: int) -> str:
    """Format a net line-change integer with a leading sign and comma separator."""
    if n > 0:
        return f"+{n:,}"
    elif n < 0:
        return f"{n:,}"
    else:
        return "0"
