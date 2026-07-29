def get_ai_prompt(case, mode):

    if mode == "SME":
        return "Simple checklist + short emails"

    elif mode == "RECRUITMENT":
        return "High volume workflow + risk flags + batching"

    elif mode == "RELOCATION":
        return "Legal compliance + canton rules + risk prevention"

    return "Default assistant"