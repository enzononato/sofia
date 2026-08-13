import asyncio
import logging
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.tenant import Tenant
from app.services import whatsapp_instance as wi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill():
    async with AsyncSessionLocal() as db:
        # Find all tenants
        tenants = (await db.execute(select(Tenant))).scalars().all()
        for tenant in tenants:
            instance_name = (tenant.settings or {}).get("whatsapp", {}).get("instance")
            if not instance_name:
                continue
            
            # Find all contacts for this tenant
            contacts = (await db.execute(select(Contact).where(Contact.tenant_id == tenant.id))).scalars().all()
            for contact in contacts:
                # We only try to fetch if not already present or if we want to force
                if not contact.profile_picture_url:
                    logger.info(f"Fetching profile for {contact.phone}...")
                    pic_url = await wi.fetch_profile_picture(instance_name, contact.phone)
                    if pic_url:
                        logger.info(f"Found picture for {contact.phone}")
                        contact.profile_picture_url = pic_url
                    else:
                        logger.info(f"No picture for {contact.phone}")
            
            await db.commit()
    logger.info("Backfill complete.")

if __name__ == "__main__":
    asyncio.run(backfill())
