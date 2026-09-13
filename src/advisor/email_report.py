"""Build and send the daily digest and monthly correlation emails."""
from __future__ import annotations

import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .analyses.activity_nudge import ActivityNudgeResult
from .analyses.correlation_report import CorrelationResult
from .analyses.outdoor_comfort import ComfortRanking
from .analyses.readiness_score import ReadinessResult
from .config import EmailConfig

logger = logging.getLogger("advisor.email")

READABLE_VAR_NAMES = {
    "pressure_hpa": "Air pressure",
    "temp_mean_c": "Temperature",
    "european_aqi": "Air quality index",
    "sleep_score": "Sleep score",
    "hrv": "HRV",
    "resting_hr": "Resting heart rate",
}


def _html_wrapper(title: str, body: str) -> str:
    return f"""\
<html>
<body style="font-family: -apple-system, Arial, sans-serif; color: #1a1a1a; max-width: 640px; margin: 0 auto;">
  <h1 style="font-size: 20px; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px;">{title}</h1>
  {body}
  <p style="color: #888; font-size: 12px; margin-top: 32px;">
    Personal Performance &amp; Environment Advisor — automated report.
  </p>
</body>
</html>"""


def build_daily_digest(
    *,
    report_date: str,
    nudge: ActivityNudgeResult,
    readiness: ReadinessResult,
    comfort_rankings: list[ComfortRanking],
    ingestion_notes: list[str],
) -> tuple[str, str, str]:
    """Returns (subject, html_body, plain_text_body)."""
    subject = f"Daily Advisor Digest — {report_date} — Readiness: {readiness.label}"

    text_lines = [f"Daily Advisor Digest — {report_date}", ""]
    html_sections = []

    if ingestion_notes:
        note_html = "".join(f"<li>{n}</li>" for n in ingestion_notes)
        html_sections.append(
            f'<div style="background:#fff3cd;padding:10px;border-radius:6px;margin-bottom:16px;">'
            f'<strong>Heads up:</strong><ul style="margin:4px 0 0 20px;">{note_html}</ul></div>'
        )
        text_lines.append("Heads up: " + "; ".join(ingestion_notes))
        text_lines.append("")

    # Readiness
    text_lines.append(f"READINESS SCORE: {readiness.overall_score} ({readiness.label})")
    text_lines.append(readiness.recommendation)
    text_lines.append("")
    html_sections.append(
        f"""
        <h2 style="font-size:16px;">Readiness Score</h2>
        <p style="font-size: 32px; font-weight: bold; margin: 4px 0; color:#2b6cb0;">
          {readiness.overall_score if readiness.overall_score is not None else "N/A"}
          <span style="font-size:16px; color:#555;">/ 100 — {readiness.label}</span>
        </p>
        <p>{readiness.recommendation}</p>
        """
    )

    # Activity nudge
    text_lines.append("ACTIVITY NUDGE")
    text_lines.append(nudge.message)
    text_lines.append("")
    html_sections.append(
        f"""
        <h2 style="font-size:16px;">Activity Nudge</h2>
        <p>{nudge.message}</p>
        """
    )

    # Outdoor comfort ranking
    text_lines.append("OUTDOOR COMFORT — NEXT 7 DAYS")
    rows_html = ""
    for rank in comfort_rankings:
        score_display = rank.comfort_score if rank.comfort_score is not None else "N/A"
        text_lines.append(f"  {rank.date}: {score_display} ({rank.label})")
        rows_html += (
            f"<tr><td style='padding:4px 8px;'>{rank.date}</td>"
            f"<td style='padding:4px 8px;'>{score_display}</td>"
            f"<td style='padding:4px 8px;'>{rank.label}</td></tr>"
        )
    text_lines.append("")
    html_sections.append(
        f"""
        <h2 style="font-size:16px;">Outdoor Comfort — Next 7 Days</h2>
        <table style="border-collapse:collapse;width:100%;">
          <tr style="background:#f0f4f8;text-align:left;">
            <th style="padding:4px 8px;">Date</th><th style="padding:4px 8px;">Score</th><th style="padding:4px 8px;">Rating</th>
          </tr>
          {rows_html}
        </table>
        """
    )

    html = _html_wrapper(f"Daily Advisor Digest — {report_date}", "".join(html_sections))
    text = "\n".join(text_lines)
    return subject, html, text


def build_monthly_report(
    *, report_period: str, results: list[CorrelationResult], notable: list[CorrelationResult]
) -> tuple[str, str, str]:
    subject = f"Monthly Correlation Report — {report_period}"

    text_lines = [f"Monthly Correlation Report — {report_period}", ""]
    if notable:
        text_lines.append("Notable correlations (|r| >= 0.3):")
        for r in notable:
            env = READABLE_VAR_NAMES.get(r.env_var, r.env_var)
            health = READABLE_VAR_NAMES.get(r.health_var, r.health_var)
            text_lines.append(f"  {env} vs {health}: r={r.r:.2f} ({r.strength}, n={r.n})")
    else:
        text_lines.append("No moderate-or-stronger correlations found this period.")
    text_lines.append("")
    text_lines.append("Full matrix:")
    for r in results:
        env = READABLE_VAR_NAMES.get(r.env_var, r.env_var)
        health = READABLE_VAR_NAMES.get(r.health_var, r.health_var)
        r_display = f"{r.r:.2f}" if r.r is not None else "N/A"
        text_lines.append(f"  {env} vs {health}: r={r_display} ({r.strength}, n={r.n})")

    notable_html = ""
    if notable:
        for r in notable:
            env = READABLE_VAR_NAMES.get(r.env_var, r.env_var)
            health = READABLE_VAR_NAMES.get(r.health_var, r.health_var)
            notable_html += f"<li><strong>{env} vs {health}</strong>: r={r.r:.2f} ({r.strength}, n={r.n})</li>"
        notable_section = f"<h2 style='font-size:16px;'>Notable Correlations</h2><ul>{notable_html}</ul>"
    else:
        notable_section = (
            "<h2 style='font-size:16px;'>Notable Correlations</h2>"
            "<p>No moderate-or-stronger correlations found this period.</p>"
        )

    matrix_rows = ""
    for r in results:
        env = READABLE_VAR_NAMES.get(r.env_var, r.env_var)
        health = READABLE_VAR_NAMES.get(r.health_var, r.health_var)
        r_display = f"{r.r:.2f}" if r.r is not None else "N/A"
        matrix_rows += (
            f"<tr><td style='padding:4px 8px;'>{env}</td><td style='padding:4px 8px;'>{health}</td>"
            f"<td style='padding:4px 8px;'>{r_display}</td><td style='padding:4px 8px;'>{r.strength}</td>"
            f"<td style='padding:4px 8px;'>{r.n}</td></tr>"
        )

    body = f"""
    {notable_section}
    <h2 style="font-size:16px;">Full Correlation Matrix</h2>
    <table style="border-collapse:collapse;width:100%;">
      <tr style="background:#f0f4f8;text-align:left;">
        <th style="padding:4px 8px;">Environmental</th><th style="padding:4px 8px;">Health</th>
        <th style="padding:4px 8px;">r</th><th style="padding:4px 8px;">Strength</th><th style="padding:4px 8px;">n</th>
      </tr>
      {matrix_rows}
    </table>
    """
    html = _html_wrapper(f"Monthly Correlation Report — {report_period}", body)
    return subject, html, "\n".join(text_lines)


def send_email(config: EmailConfig, subject: str, html_body: str, text_body: str, *, attempts: int = 3) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.from_address
    msg["To"] = config.to_address
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as server:
                if config.use_tls:
                    server.starttls()
                server.login(config.smtp_username, config.smtp_password)
                server.sendmail(config.from_address, [config.to_address], msg.as_string())
            logger.info("Sent email %r to %s", subject, config.to_address)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Email send failed (attempt %d/%d): %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(2 * attempt)
    assert last_exc is not None
    logger.error("Giving up sending email %r after %d attempts", subject, attempts)
    raise last_exc
