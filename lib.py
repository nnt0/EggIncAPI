import base64
from typing import List, Optional
from math import fsum
import math
import httpx

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
        query_coop_req = ei.QueryCoopRequest(
            rinfo=ei.BasicRequestInfo(
                ei_user_id=self.user_id
            ),
            contract_identifier=contract_id,
            coop_identifier=coop_code,
            league=0,
            grade=ei.ContractPlayerGrade.GRADE_A,
            client_version=self.current_client_version
        )

        response = await self.post_to("query_coop", query_coop_req)

        query_coop_resp = ei.QueryCoopResponse().parse(base64.b64decode(response.text))

        return query_coop_resp

    async def get_coop_grade(self, contract_id: str, coop_code: str) -> ei.ContractPlayerGrade:
        coop_status: ei.ContractCoopStatusResponse = await self.get_coop_status(contract_id, coop_code)
        bot_first_contact: ei.EggIncFirstContactResponse = await self.bot_first_contact(coop_status.creator_id)

        return bot_first_contact.backup.contracts.contracts[0].grade

    async def get_periodicals(self) -> ei.PeriodicalsResponse:
        periodicals_req = ei.GetPeriodicalsRequest(
            user_id=self.user_id,
            current_client_version=self.current_client_version
        )

        response = await self.post_to("get_periodicals", periodicals_req)

        authenticated_message = ei.AuthenticatedMessage().parse(base64.b64decode(response.text))

        periodicals_resp = ei.PeriodicalsResponse().parse(authenticated_message.message)

        return periodicals_resp

    async def get_current_contracts(self) -> List[ei.Contract]:
        periodicals = await self.get_periodicals()

        if periodicals.contracts.warning_message != "":
            print("Contracts contained a warning message: %s", periodicals.contracts.warning_message)

        # contracts = list(
        #     filter(
        #         lambda contract: contract.identifier != "first-contract" and contract.max_coop_size != 0, periodicals.contracts.contracts
        #     )
        # )

        return periodicals.contracts.contracts

    async def get_coop_status(self, contract_id: str, coop_code: str) -> ei.ContractCoopStatusResponse:
        coop_status_request = ei.ContractCoopStatusRequest(
            rinfo=ei.BasicRequestInfo(
                ei_user_id=self.user_id
            ),
            contract_identifier=contract_id,
            coop_identifier=coop_code,
            user_id=self.user_id
        )

        response = await self.post_to("coop_status", coop_status_request)

        authenticated_message = ei.AuthenticatedMessage().parse(base64.b64decode(response.text))

        coop_status_response = ei.ContractCoopStatusResponse().parse(authenticated_message.message)

        return coop_status_response

    async def bot_first_contact(self, user_id: Optional[str] = None) -> ei.EggIncFirstContactResponse:
        if user_id is None:
            user_id = self.user_id

        first_contact_req = ei.EggIncFirstContactRequest(
            rinfo=ei.BasicRequestInfo(ei_user_id=user_id),
            ei_user_id=user_id
        )

        response = await self.post_to("bot_first_contact", first_contact_req)

        first_contact_resp = ei.EggIncFirstContactResponse().parse(base64.b64decode(response.text))

        return first_contact_resp

class CoOp:
    contract: ei.Contract
    coop_code: str
    grade: ei.ContractPlayerGrade
    goals: List[ei.ContractGoal]

    def __init__(self, contract: ei.Contract, coop_code: str, grade: ei.ContractPlayerGrade) -> None:
        self.contract = contract
        self.coop_code = coop_code
        self.grade = grade

        for grade_spec in self.contract.grade_specs:
            if grade_spec.grade is self.grade:
                self.goals = grade_spec.goals
                break

    async def get_status(self, eggincapi: EggIncApi) -> ei.ContractCoopStatusResponse:
        coop_stats = await eggincapi.get_coop_status(self.contract.identifier, self.coop_code)

        return coop_stats

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
        highest_goal = self.goals[0]
        for goal in self.goals:
            if goal.target_amount > highest_goal.target_amount:
                highest_goal = goal

        return highest_goal

    def get_is_coop_finished(self, coop_stats: ei.ContractCoopStatusResponse) -> bool:
        return coop_stats.total_amount >= self.get_highest_goal().target_amount

    def get_is_coop_full(self, coop_stats: ei.ContractCoopStatusResponse) -> bool:
        return self.contract.max_coop_size == len(coop_stats.contributors)

    def get_has_time_run_out(self, coop_stats: ei.ContractCoopStatusResponse) -> bool:
        return coop_stats.seconds_remaining < 0.0
