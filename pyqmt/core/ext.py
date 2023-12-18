def shift(arr, start, offset):
    """在numpy数组arr中,找到start(或者最接近的一个）,取offset对应的元素。

    要求`arr`已排序。`offset`为正,表明向后移位；`offset`为负,表明向前移位

    Examples:
        >>> arr = [20050104, 20050105, 20050106, 20050107, 20050110, 20050111]
        >>> shift(arr, 20050104, 1)
        20050105

        >>> shift(arr, 20050105, -1)
        20050104

        >>> # 起始点已右越界,且向右shift,返回起始点
        >>> shift(arr, 20050120, 1)
        20050120


    Args:
        arr : 已排序的数组
        start : numpy可接受的数据类型
        offset (int): [description]

    Returns:
        移位后得到的元素值
    """
    pos = np.searchsorted(arr, start, side="right")

    if pos + offset - 1 >= len(arr):
        return start
    else:
        return arr[pos + offset - 1]
    
def count_between(arr, start, end):
    """计算数组中，`start`元素与`end`元素之间共有多少个元素

    要求arr必须是已排序。计算结果会包含区间边界点。

    Examples:
        >>> arr = [20050104, 20050105, 20050106, 20050107, 20050110, 20050111]
        >>> count_between(arr, 20050104, 20050111)
        6

        >>> count_between(arr, 20050104, 20050109)
        4
    """
    pos_start = np.searchsorted(arr, start, side="right")
    pos_end = np.searchsorted(arr, end, side="right")

    counter = pos_end - pos_start + 1
    if start < arr[0]:
        counter -= 1
    if end > arr[-1]:
        counter -= 1

    return counter

def floor(arr, item):
    """
    在数据arr中，找到小于等于item的那一个值。如果item小于所有arr元素的值，返回arr[0];如果item
    大于所有arr元素的值，返回arr[-1]

    与`minute_frames_floor`不同的是，本函数不做回绕与进位.

    Examples:
        >>> a = [3, 6, 9]
        >>> floor(a, -1)
        3
        >>> floor(a, 9)
        9
        >>> floor(a, 10)
        9
        >>> floor(a, 4)
        3
        >>> floor(a,10)
        9

    Args:
        arr:
        item:

    Returns:

    """
    if item < arr[0]:
        return arr[0]
    index = np.searchsorted(arr, item, side="right")
    return arr[index - 1]
