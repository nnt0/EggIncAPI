import base64
import httpx
from math import fsum
import math
from typing import List

import ei

class EggIncApi:
    base_url: str
    user_id: str
    current_client_version: int
    session = httpx.AsyncClient(timeout=httpx.Timeout(timeout=15.0), http2=True)

    def __init__(self, base_url: str, user_id: str, current_client_version: int) -> None:
        self.base_url = base_url
        self.user_id = user_id
        self.current_client_version = current_client_version

    async def post_to(self, endpoint: str, data) -> httpx.Response:
        url = self.base_url.format(endpoint)
        data = {
            'data': base64.b64encode(
                bytes(data)
            )
            .decode('utf-8')
        }
        response = await self.session.post(url=url, data=data)

        return response

    async def query_coop(self, contract_id: str, coop_code: str) -> ei.QueryCoopResponse:
        """Makes the request with league set to 1 (aka standard). Meaning different_league == True means the coop is elite"""
        query_coop_req = ei.QueryCoopRequest(
            contract_identifier=contract_id,
            coop_identifier=coop_code,
            league=1,
            client_version=self.current_client_version
        )

        response = await self.post_to("query_coop", query_coop_req)

        query_coop_resp = ei.QueryCoopResponse().parse(base64.b64decode(response.text))

        return query_coop_resp

    async def get_coop_league(self, contract_id: str, coop_code: str) -> int:
        "returns: 0 means elite, 1 means standard"
        query_coop_resp = await self.query_coop(contract_id, coop_code)

        if query_coop_resp.different_league:
            return 0

        return 1

    async def get_periodicals(self) -> ei.PeriodicalsResponse:
        periodicals_req = ei.GetPeriodicalsRequest(user_id=self.user_id, current_client_version=self.current_client_version)

        response = await self.post_to("get_periodicals", periodicals_req)

        authenticated_message = ei.AuthenticatedMessage().parse(base64.b64decode(response.text))

        periodicals_resp = ei.PeriodicalsResponse().parse(authenticated_message.message)

        return periodicals_resp

    async def get_current_contracts(self) -> List[ei.Contract]:
        periodicals = await self.get_periodicals()

        if periodicals.contracts.warning_message != "":
            print(f"Contracts contained a warning message: {periodicals.contracts.warning_message}")

        # contracts = list(
        #     filter(
        #         lambda contract: contract.identifier != "first-contract" and contract.max_coop_size != 0, 
        #     )
        # )

        return periodicals.contracts.contracts

    async def get_coop_status(self, contract_id: str, coop_code: str) -> ei.ContractCoopStatusResponse:
        coop_status_request = ei.ContractCoopStatusRequest(contract_identifier=contract_id, coop_identifier=coop_code, user_id=self.user_id)

        response = await self.post_to("coop_status", coop_status_request)

        authenticated_message = ei.AuthenticatedMessage().parse(base64.b64decode(response.text))

        coop_status_response = ei.ContractCoopStatusResponse().parse(authenticated_message.message)

        return coop_status_response

    async def bot_first_contact(self) -> ei.EggIncFirstContactResponse:
        first_contact_req = ei.EggIncFirstContactRequest(user_id=self.user_id)

        response = await self.post_to("bot_first_contact", first_contact_req)

        first_contact_resp = ei.EggIncFirstContactResponse().parse(response.content)

        return first_contact_resp

class CoOp:
    contract: ei.Contract
    coop_code: str
    league: int
    """0 means elite, 1 means standard"""

    def __init__(self, contract: ei.Contract, coop_code: str, league: int) -> None:
        self.contract = contract
        self.coop_code = coop_code
        self.league = league

    async def get_status(self, eggincapi: EggIncApi) -> ei.ContractCoopStatusResponse:
        return await eggincapi.get_coop_status(self.contract.identifier, self.coop_code)

    def get_eggs_shipping_per_second(self, coop_stats: ei.ContractCoopStatusResponse) -> int:
        total_eggs_shipping_per_second = fsum(
            map(
                lambda contributor: min(contributor.contribution_rate, contributor.production_params.sr),
                coop_stats.contributors
            )
        )

        return total_eggs_shipping_per_second

    def get_projection(self, coop_stats: ei.ContractCoopStatusResponse) -> int:
        total_eggs_shipping_per_second = self.get_eggs_shipping_per_second(coop_stats)
        projection = total_eggs_shipping_per_second * coop_stats.seconds_remaining + coop_stats.total_amount

        return projection

    def get_seconds_until_finished(self, coop_stats: ei.ContractCoopStatusResponse) -> float:
        total_eggs_shipping_per_second = self.get_eggs_shipping_per_second(coop_stats)

        if total_eggs_shipping_per_second == 0:
            return math.inf

        return (self.get_highest_goal().target_amount - coop_stats.total_amount) / total_eggs_shipping_per_second

    def get_highest_goal(self) -> ei.ContractGoal:
        goals = self.contract.goal_sets[self.league].goals
        highest_goal = goals[0]
        for goal in goals:
            if goal.target_amount > highest_goal.target_amount:
                highest_goal = goal

        return highest_goal

    def get_is_coop_finished(self, coop_stats: ei.ContractCoopStatusResponse) -> bool:
        return coop_stats.total_amount >= self.get_highest_goal().target_amount

    def get_is_coop_full(self, coop_stats: ei.ContractCoopStatusResponse) -> bool:
        return self.contract.max_coop_size == len(coop_stats.contributors)

    def get_has_time_run_out(self, coop_stats: ei.ContractCoopStatusResponse) -> bool:
        return coop_stats.seconds_remaining < 0.0
