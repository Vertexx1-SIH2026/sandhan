from fastapi import APIRouter

from app.api.v1 import auth
from app.api.v1.investigator import (
    upload, graph, analytics, nlp, evidence, links, baseline, audit as inv_audit,
)
from app.api.v1.admin import users as admin_users, audit as admin_audit

api_router = APIRouter()

api_router.include_router(auth.router)

# investigator namespace
for r in (upload, graph, analytics, links, nlp, evidence, baseline, inv_audit):
    api_router.include_router(r.router)

# admin namespace
api_router.include_router(admin_users.router)
api_router.include_router(admin_audit.router)
