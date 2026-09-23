from litellm.integrations.custom_logger import CustomLogger

class ForwardRequestIdsHook(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        data.setdefault("extra_headers", {})

        call_id = data.get("litellm_call_id")
        if call_id:
            data["extra_headers"]["x-litellm-call-id"] = call_id

        client_headers = (data.get("proxy_server_request") or {}).get("headers") or {}
        client_req_id = client_headers.get("x-request-id") or client_headers.get("x-client-request-id")
        if client_req_id:
            data["extra_headers"]["x-client-request-id"] = client_req_id

        return data

proxy_handler_instance = ForwardRequestIdsHook()