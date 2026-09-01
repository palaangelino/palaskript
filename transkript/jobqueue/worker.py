"""Bir isi ayri SUREC icinde calistiran giris noktasi.

Neden is parcacigi degil surec:

1. Bellek. CTranslate2 model bellegini surec omru boyunca tutuyor ve isletim
   sistemine geri vermiyor. 8 GB'lik makinede arka arkaya on video islenirse
   bu birikim olumcul. Surec her isin sonunda oldugunde bellek kesin doniyor.
2. Iptal. Uzun bir cikarim cagrisinin ortasindaki is parcacigini kesmek mumkun
   degil; sureci sonlandirmak her zaman mumkun.
3. Cokme yalitimi. Bozuk bir medya dosyasi yerel kutuphanede segfault'a yol
   acarsa sadece bu is oluyor, uygulama ayakta kaliyor.

Bu modul Windows'un spawn baslatma yonteminde yeniden import edildigi icin
modul seviyesinde yan etki barindirmamali.
"""

from __future__ import annotations

import multiprocessing as mp
import traceback
from typing import Any

from ..config import Settings
from ..datatypes import SourceInfo


def run_in_process(
    payload: dict[str, Any],
    progress_queue: mp.Queue[tuple[str, Any]],
    cancel_event: Any,
) -> None:
    """Alt surecin giris noktasi. Sonuclari kuyruga yaziyor."""
    try:
        from ..pipeline import JobCancelled, Progress, run_job
        from ..resources import lower_process_priority

        # 6 saatlik is sururken bilgisayarin kullanilabilir kalmasi icin.
        lower_process_priority()

        source = SourceInfo.from_dict(payload["source"])
        settings = Settings.from_dict(payload["settings"])
        job_id = payload["job_id"]

        def on_progress(event: Progress) -> None:
            progress_queue.put(
                (
                    "progress",
                    {
                        "stage": event.stage,
                        "fraction": event.fraction,
                        "message": event.message,
                        "eta": event.eta_seconds,
                    },
                )
            )

        def cancelled() -> bool:
            return bool(cancel_event.is_set())

        try:
            result = run_job(
                source,
                settings,
                job_id=job_id,
                progress=on_progress,
                cancel=cancelled,
                use_subtitles=bool(payload.get("use_subtitles")),
            )
        except JobCancelled:
            progress_queue.put(("cancelled", None))
            return

        progress_queue.put(
            (
                "done",
                {
                    "pdf_path": str(result.pdf_path) if result.pdf_path else None,
                    "txt_path": str(result.txt_path) if result.txt_path else None,
                    "audio_path": str(result.audio_path) if result.audio_path else None,
                    "from_subtitles": result.from_subtitles,
                    "elapsed": result.elapsed_seconds,
                    "warnings": result.warnings,
                    "word_count": result.doc.word_count,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001 - her hata ana surece tasinmali
        progress_queue.put(("error", f"{exc}\n\n{traceback.format_exc(limit=6)}"))
