"""Sign-WITHOUT-send: prove the agent key produces a valid HL L1 signature, no POST.

This is the second execution gate. It NEVER sends anything and NEVER logs the key:
it loads the agent key (provisioned by the owner on the VPS), signs the exact order
action the dry-run built, and recovers the signer to confirm the signature is valid
and comes from the AUTHORIZED agent. Only then is a real order even conceivable.

The eth/SDK deps live ONLY on the VPS, so they are imported lazily inside the
functions — importing this module (and running the whole test suite) needs nothing
beyond stdlib. A missing dep fails LOUDLY with the install hint, not cryptically.
"""

from __future__ import annotations

from dataclasses import dataclass

EXCHANGE_CHAIN_ID = 1337   # HL "Exchange" EIP-712 domain id (not an L1 chain id)
ZERO_ADDR = "0x0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class SignCheck:
    """Result of the sign-without-send gate. ok = the key is ONE of the agents
    authorized on-chain for the master AND its signature recovers back to it."""

    agent_address: str                  # derived from the key (public, safe to show)
    authorized_agents: tuple[str, ...]  # ALL agents registered on-chain for the master
    signature: dict                     # {r, s, v} — proof signing succeeded
    recovered: str | None               # address recovered from the signature (None if skipped)

    @property
    def is_authorized(self) -> bool:
        a = self.agent_address.lower()
        return any(a == x.lower() for x in self.authorized_agents)

    @property
    def recovers_to_agent(self) -> bool:
        return self.recovered is not None and self.recovered.lower() == self.agent_address.lower()

    @property
    def ok(self) -> bool:
        return self.is_authorized and self.recovers_to_agent


def _require(modname: str):
    import importlib
    try:
        return importlib.import_module(modname)
    except ImportError as e:   # pragma: no cover - exercised only off-VPS
        raise RuntimeError(
            f"{modname} is required to sign (VPS only). Install the quarantined deps: "
            f"pip install hyperliquid-python-sdk eth-account") from e


def agent_address_from_key(agent_key: str) -> str:
    """Public address of the agent wallet the key controls. Never logs the key."""
    eth_account = _require("eth_account")
    return eth_account.Account.from_key(agent_key).address


def sign_order_action(agent_key: str, action: dict, nonce: int, *, is_mainnet: bool = True,
                      vault_address: str | None = None, expires_after: int | None = None) -> dict:
    """Sign an L1 order action with the SDK. Returns {r,s,v}. No network call.
    Tolerates both the newer (expires_after) and older sign_l1_action signatures."""
    eth_account = _require("eth_account")
    signing = _require("hyperliquid.utils.signing")
    wallet = eth_account.Account.from_key(agent_key)
    try:
        return signing.sign_l1_action(wallet, action, vault_address, nonce, expires_after, is_mainnet)
    except TypeError:          # older SDK without expires_after
        return signing.sign_l1_action(wallet, action, vault_address, nonce, is_mainnet)


def recover_l1_signer(action: dict, signature: dict, nonce: int, *, is_mainnet: bool = True,
                      vault_address: str | None = None, expires_after: int | None = None) -> str:
    """Recover the address that produced `signature` over this action. Best-effort:
    rebuilds the EIP-712 phantom-agent digest from SDK internals and recovers it."""
    eth_account = _require("eth_account")
    typed_data = _require("eth_account.messages")
    signing = _require("hyperliquid.utils.signing")
    try:
        h = signing.action_hash(action, vault_address, nonce, expires_after)
    except TypeError:          # older SDK without expires_after
        h = signing.action_hash(action, vault_address, nonce)
    phantom = signing.construct_phantom_agent(h, is_mainnet)
    full = {
        "domain": {"chainId": EXCHANGE_CHAIN_ID, "name": "Exchange",
                   "verifyingContract": ZERO_ADDR, "version": "1"},
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"}],
            "Agent": [{"name": "source", "type": "string"},
                      {"name": "connectionId", "type": "bytes32"}],
        },
        "primaryType": "Agent",
        "message": phantom,
    }
    encoded = typed_data.encode_typed_data(full_message=full)
    vrs = (signature["v"], int(signature["r"], 16), int(signature["s"], 16))
    return eth_account.Account.recover_message(encoded, vrs=vrs)
