"""SCIM 2.0 User provisioning API package.

Endpoints: POST, GET (single + list), PATCH, PUT, DELETE /api/v1/admin/scim/Users
Auth:       SCIM bearer token (separate from staff JWTs — see scim_auth.py)
RFC refs:   RFC 7643 (SCIM Schema), RFC 7644 (SCIM Protocol)
Design:     design.md §7.4 AIR-032
US-060
"""
