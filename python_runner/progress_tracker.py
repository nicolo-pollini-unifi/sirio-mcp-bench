"""
This module provides progress visualization utilities for CLI execution tracking.
"""

import os
import sys
import time
import logging

logger = logging.getLogger(__name__)

class ProgressTracker:
    """
    Visual progress logger displaying colored terminal progress bars, ETA, and stats.
    """
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    WHITE = "\033[37m"

    def __init__(self, total_evals: int):
        """
        Initializes the progress tracker with the total number of expected evaluations.

        Args:
            total_evals: The total count of runs/samples to monitor.
        """
        self.total_evals = total_evals
        self.completed_evals = 0
        self.start_time = time.time()

    def _get_ansi_support(self) -> bool:
        """
        Detects if the current output terminal supports ANSI escape sequences.
        """
        if not sys.stdout.isatty():
            return False
        if os.name == 'nt':
            if 'COLORTERM' in os.environ or 'TERM' in os.environ:
                return True
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except Exception:
                return False
        return True

    def _format(self, text: str, color: str, bold: bool = False) -> str:
        """
        Applies ANSI color formatting if supported by the stdout terminal.
        """
        if self._get_ansi_support():
            bold_prefix = self.BOLD if bold else ""
            return f"{bold_prefix}{color}{text}{self.RESET}"
        return text

    def get_progress_bar(self, count: int) -> str:
        """
        Generates a text-based progress bar matching the current progress ratio.

        Args:
            count: The number of completed items.

        Returns:
            A formatted progress bar string.
        """
        if self.total_evals <= 0:
            return ""
        length = 20
        filled_length = int(round(length * count / self.total_evals))
        
        try:
            bar = "█" * filled_length + "░" * (length - filled_length)
            bar.encode(sys.stdout.encoding or 'utf-8')
        except Exception:
            bar = "#" * filled_length + "-" * (length - filled_length)
            
        pct = (count / self.total_evals) * 100
        colored_bar = self._format(bar, self.GREEN, bold=True)
        colored_pct = self._format(f"{pct:.1f}%", self.CYAN, bold=True)
        return f"[{colored_bar}] {colored_pct}"

    def start_sample(self, case_id: str, with_mcp: bool, sample_index: int, total_samples: int):
        """
        Logs a visual header when a new sample execution begins.

        Args:
            case_id: The ID of the test case.
            with_mcp: True if running in MCP mode, False otherwise.
            sample_index: Index of the current sample.
            total_samples: Total sample count per case.
        """
        mode_str = "With MCP" if with_mcp else "No MCP"
        
        title = self._format(
            f"[Progress] Running evaluation {self.completed_evals + 1}/{self.total_evals}",
            self.YELLOW,
            bold=True
        )
        details = self._format(
            f"Case: {case_id} | Mode: {mode_str} | Sample: {sample_index + 1}/{total_samples}",
            self.CYAN
        )
        border = self._format("=" * 80, self.BLUE)
        
        logger.info(
            f"\n{border}\n"
            f">>> {title}\n"
            f">>> {details}\n"
            f"{border}"
        )

    def complete_sample(self):
        """
        Increments completed counter and prints elapsed duration, ETA, and progress bar.
        """
        self.completed_evals += 1
        elapsed = time.time() - self.start_time
        avg_time = elapsed / self.completed_evals
        remaining = self.total_evals - self.completed_evals
        eta = avg_time * remaining
        eta_str = time.strftime('%H:%M:%S', time.localtime(time.time() + eta))
        
        bar_str = self.get_progress_bar(self.completed_evals)
        title = self._format(
            f"[Progress] Completed {self.completed_evals}/{self.total_evals}",
            self.GREEN,
            bold=True
        )
        stats = self._format(
            f"Elapsed: {elapsed:.1f}s | Avg: {avg_time:.1f}s/sample | "
            f"Est. Remaining: {eta:.1f}s (ETA: {eta_str})",
            self.WHITE
        )
        border = self._format("=" * 80, self.BLUE)
        
        logger.info(
            f"\n{border}\n"
            f">>> {title} {bar_str}\n"
            f">>> {stats}\n"
            f"{border}"
        )
