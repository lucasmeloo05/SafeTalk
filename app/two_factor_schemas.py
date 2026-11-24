from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool

class TwoFactorChallengeResponse(BaseModel):
    two_factor_required: Literal[True]
    challenge: str
    expires_in: int

class FactorProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9]+$")
    recovery: StrictBool = False

class ChallengeProof(FactorProof):
    challenge: str = Field(min_length=20, max_length=128)

class StrongProof(FactorProof):
    password: SecretStr = Field(max_length=128)

class SetupProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(max_length=128)
