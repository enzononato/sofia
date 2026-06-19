"""
One-off: enable Sofia's multimodal mode (audio/image/PDF) for existing clinics.

Usage:
    python -m scripts.enable_multimodal            # all active tenants
    python -m scripts.enable_multimodal <slug>     # a single tenant by slug

Safe to re-run (idempotent). New tenants keep the default (off) until they
toggle it in Configurações → Inteligência Artificial.
"""

import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.tenant import Tenant


async def main(slug: str | None) -> None:
    async with AsyncSessionLocal() as db:
        query = select(Tenant)
        if slug:
            query = query.where(Tenant.slug == slug)
        tenants = (await db.execute(query)).scalars().all()

        if not tenants:
            print(f"No tenant found{f' for slug={slug}' if slug else ''}.")
            return

        changed = 0
        for t in tenants:
            cfg = dict(t.ai_config or {})
            if not cfg.get("multimodal_enabled"):
                cfg["multimodal_enabled"] = True
                t.ai_config = cfg  # reassign so SQLAlchemy flags the JSONB dirty
                changed += 1
                print(f"  + {t.name} ({t.slug}): multimodal ligado")
            else:
                print(f"  = {t.name} ({t.slug}): já estava ligado")
        await db.commit()
        print(f"\nConcluído: {changed}/{len(tenants)} clínica(s) atualizada(s).")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(arg))
