from fastapi import APIRouter

from app.api.v1.routes import appointments, auth, contacts, services, tenants, users, webhooks, whatsapp

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(tenants.router)
api_router.include_router(whatsapp.router)
api_router.include_router(services.router)
api_router.include_router(appointments.router)
api_router.include_router(contacts.router)
api_router.include_router(users.router)
api_router.include_router(webhooks.router)
