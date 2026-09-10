from pkg import helper


def actual():
    return helper()


def parameter(helper):
    return helper()


def local():
    helper = lambda: 'local'
    return helper()
