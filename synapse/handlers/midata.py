import inspect
import logging
import json
from typing import TYPE_CHECKING, Any, Dict, Generic, List, Optional, TypeVar, Union
from urllib.parse import urlencode, urlparse

import attr
import pymacaroons
from authlib.common.security import generate_token
from authlib.jose import JsonWebToken, jwt
from authlib.oauth2.auth import ClientAuth
from authlib.oauth2.rfc6749.parameters import prepare_grant_uri
from authlib.oidc.core import CodeIDToken, UserInfo
from authlib.oidc.discovery import OpenIDProviderMetadata, get_well_known_url
from jinja2 import Environment, Template
from pymacaroons.exceptions import (
    MacaroonDeserializationException,
    MacaroonInitException,
    MacaroonInvalidSignatureException,
)
from typing_extensions import TypedDict

from twisted.web.client import readBody
from twisted.web.http_headers import Headers

from synapse.config import ConfigError
from synapse.config.oidc import OidcProviderClientSecretJwtKey, OidcProviderConfig
from synapse.handlers.sso import MappingException, UserAttributes
from synapse.http.site import SynapseRequest
from synapse.logging.context import make_deferred_yieldable
from synapse.types import JsonDict, UserID, map_username_to_mxid_localpart
from synapse.util import Clock, json_decoder
from synapse.util.caches.cached_call import RetryOnExceptionCachedCall
from synapse.util.macaroons import get_value_from_macaroon, satisfy_expiry
from synapse.handlers.oidc import *


if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)





# Used to clear out "None" values in templates
def jinja_finalize(thing: Any) -> Any:
    return thing if thing is not None else ""


env = Environment(finalize=jinja_finalize)


@attr.s(slots=True, frozen=True, auto_attribs=True)
class JinjaOidcMappingConfig:
    subject_claim: str
    localpart_template: Optional[Template]
    display_name_template: Optional[Template]
    email_template: Optional[Template]
    extra_attributes: Dict[str, Template]



class MIDATAMappingProvider(OidcMappingProvider[JinjaOidcMappingConfig]):
    """An implementation of a mapping provider based on Jinja templates.

    This is the default mapping provider.
    """

    def __init__(self, config: JinjaOidcMappingConfig):
        self._config = config
        logger.info("Super Midata MappingProvider loaded")

    @staticmethod
    def parse_config(config: dict) -> JinjaOidcMappingConfig:
        subject_claim = config.get("subject_claim", "sub")

        def parse_template_config(option_name: str) -> Optional[Template]:
            if option_name not in config:
                return None
            try:
                return env.from_string(config[option_name])
            except Exception as e:
                raise ConfigError("invalid jinja template", path=[option_name]) from e

        localpart_template = parse_template_config("localpart_template")
        display_name_template = parse_template_config("display_name_template")
        email_template = parse_template_config("email_template")

        extra_attributes = {}  # type Dict[str, Template]
        if "extra_attributes" in config:
            extra_attributes_config = config.get("extra_attributes") or {}
            if not isinstance(extra_attributes_config, dict):
                raise ConfigError("must be a dict", path=["extra_attributes"])

            for key, value in extra_attributes_config.items():
                try:
                    extra_attributes[key] = env.from_string(value)
                except Exception as e:
                    raise ConfigError(
                        "invalid jinja template", path=["extra_attributes", key]
                    ) from e

        return JinjaOidcMappingConfig(
            subject_claim=subject_claim,
            localpart_template=localpart_template,
            display_name_template=display_name_template,
            email_template=email_template,
            extra_attributes=extra_attributes,
        )

    def get_remote_user_id(self, userinfo: UserInfo) -> str:
        user_json = json.loads(str(userinfo).replace("'", '"').replace("True", "true").replace("False", "false"))
        logger.info("MIDATA User JSON")
        logger.info(user_json)
        remote_user_id = user_json["entry"][0]["resource"]["identifier"][0]["value"]
        logger.info("remote_user_id: " + remote_user_id)
        return remote_user_id

    async def map_user_attributes(
        self, userinfo: UserInfo, token: Token, failures: int
    ) -> UserAttributeDict:
        localpart = None

        if self._config.localpart_template:
            localpart = self._config.localpart_template.render(user=userinfo).strip()

            # Ensure only valid characters are included in the MXID.
            localpart = map_username_to_mxid_localpart(localpart)

            # Append suffix integer if last call to this function failed to produce
            # a usable mxid.
            localpart += str(failures) if failures else ""

        def render_template_field(template: Optional[Template]) -> Optional[str]:
            if template is None:
                return None
            return template.render(user=userinfo).strip()

        display_name = render_template_field(self._config.display_name_template)
        if display_name == "":
            display_name = None
            
        logger.info("display_name: " + display_name)
        emails: List[str] = []
        email = render_template_field(self._config.email_template)
        if email:
            emails.append(email)

        logger.info("email: " + email)
        return UserAttributeDict(
            localpart=localpart, display_name=display_name, emails=emails
        )

    async def get_extra_attributes(self, userinfo: UserInfo, token: Token) -> JsonDict:
        extras: Dict[str, str] = {}
        for key, template in self._config.extra_attributes.items():
            try:
                extras[key] = template.render(user=userinfo).strip()
            except Exception as e:
                # Log an error and skip this value (don't break login for this).
                logger.error("Failed to render OIDC extra attribute %s: %s" % (key, e))
        return extras

