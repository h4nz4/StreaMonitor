import parameters


def confirm_deletes(user_agent: str):
    ua = user_agent.lower()
    mobile_strings = ['android', 'iphone', 'ipad', 'mobile']
    cdel = parameters.WEB_CONFIRM_DELETES
    if cdel and cdel != "MOBILE":
        return True
    elif cdel:
        return any(mobile in ua for mobile in mobile_strings)
    else:
        return False