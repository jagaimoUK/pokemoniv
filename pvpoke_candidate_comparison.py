"""Pure comparison helpers shared by the recommendation pass.

Equivalent performance vectors form one group for comparisons, but every
supplied IV remains in the output audit in its original order.
"""


def rating_dominators(ivs, vectors, equivalents):
    groups = list(equivalents)
    dominating_groups = {iv: set() for iv in groups}
    for index, left in enumerate(groups):
        for right in groups[index + 1:]:
            left_better = right_better = False
            for a, b in zip(vectors[left], vectors[right]):
                if a > b:
                    left_better = True
                elif b > a:
                    right_better = True
                if left_better and right_better:
                    break
            else:
                if left_better:
                    dominating_groups[right].add(left)
                elif right_better:
                    dominating_groups[left].add(right)
    group_for = {member: owner for owner, alternatives in equivalents.items()
                 for member in (owner, *alternatives)}
    expanded = {owner: [iv for iv in ivs if group_for[iv] in others]
                for owner, others in dominating_groups.items()}
    return {iv: expanded[group_for[iv]] for iv in ivs}


def rival_summaries(scores):
    """Best rival and whether any rival is <=500, excluding the whole group.

    Two maxima preserve ties: removing one group may leave another tied group.
    Include dominated groups too; a win is unique only against ALL rivals.
    """
    top = second = float('-inf')
    losses = 0
    for value in scores.values():
        if value >= top:
            top, second = value, top
        elif value > second:
            second = value
        losses += value <= 500
    return {iv: (None if len(scores) == 1 else second if value == top else top,
                 losses > int(value <= 500))
            for iv, value in scores.items()}
