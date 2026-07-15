#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from acp import (
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    SetSessionConfigOptionResponse,
    SetSessionModeResponse,
    run_agent,
    update_agent_message_text,
)
from acp.schema import SessionConfigOptionSelect, SessionConfigSelectOption, SessionMode, SessionModeState


class FixtureAgent:
    def on_connect(self, connection) -> None:
        self.connection = connection

    async def initialize(self, protocol_version, **kwargs):
        del kwargs
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(self, cwd, mcp_servers, **kwargs):
        del cwd, mcp_servers, kwargs
        return NewSessionResponse(
            session_id="fixture-session",
            modes=SessionModeState(
                current_mode_id="plan",
                available_modes=[
                    SessionMode(id="plan", name="Plan"),
                    SessionMode(id="agent-full-access", name="Full access"),
                ],
            ),
            config_options=self._config_options(),
        )

    async def set_config_option(self, config_id, session_id, value, **kwargs):
        del config_id, session_id, value, kwargs
        return SetSessionConfigOptionResponse(config_options=self._config_options())

    async def set_session_mode(self, session_id, mode_id, **kwargs):
        del session_id, mode_id, kwargs
        return SetSessionModeResponse()

    async def prompt(self, session_id, prompt, **kwargs):
        del prompt, kwargs
        await self.connection.session_update(session_id, update_agent_message_text("fixture ACP output"))
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id, **kwargs):
        del session_id, kwargs

    @staticmethod
    def _config_options():
        return [
            SessionConfigOptionSelect(
                type="select",
                id="model",
                name="Model",
                current_value="fixture-model",
                options=[SessionConfigSelectOption(value="fixture-model", name="Fixture model")],
            )
        ]


asyncio.run(run_agent(FixtureAgent()))
