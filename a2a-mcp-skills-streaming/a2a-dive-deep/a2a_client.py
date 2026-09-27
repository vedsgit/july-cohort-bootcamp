import httpx

from a2a.client import (
    A2ACardResolver,
    ClientConfig,
    create_client,
)

from a2a.helpers import get_stream_response_text, new_text_message

from a2a.types import (
    Role,
    SendMessageRequest,
)


async def call_a2a_agent(
    agent_url: str,
    request_text: str,
) -> str:

    async with httpx.AsyncClient() as http:

        # -----------------------------
        # 1. Discover Agent
        # -----------------------------

        resolver = A2ACardResolver(
            httpx_client=http,
            base_url=agent_url,
        )

        agent_card = await resolver.get_agent_card()

        print(
            f"\nCalling A2A agent: {agent_card.name}"
        )

        # -----------------------------
        # 2. Build A2A client
        # -----------------------------

        config = ClientConfig(
            streaming=False
        )

        client = await create_client(
            agent=agent_card,
            client_config=config,
        )

        # -----------------------------
        # 3. Create A2A message
        # -----------------------------

        message = new_text_message(
            request_text,
            role=Role.ROLE_USER,
        )

        request = SendMessageRequest(
            message=message
        )

        # -----------------------------
        # 4. Send to remote agent
        # -----------------------------

        # Status lines are progress. The specialist's answer is the
        # artifact or the completed task, so those win over a status line.
        answer = ""
        status_text = ""

        async for event in client.send_message(
            request
        ):

            text = get_stream_response_text(event).strip()
            if not text:
                continue
            if event.HasField("status_update"):
                status_text = text
            else:
                answer = text

        await client.close()

        return answer or status_text or "The specialist returned no text."