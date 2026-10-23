"""Coverage checks for administrator-approved literal entity aliases.

Not a query parser or answer generator: ambiguous scope still belongs to the LLM
and clarification flow. This catches omission, not every possible wrong operator.
"""
import re
import unicodedata


def missing_entity_constraints(question, plan, rules):
    question = unicodedata.normalize('NFKC', question).casefold()
    missing = []
    for rule in rules:
        mentioned = []
        for canonical, aliases in rule['values'].items():
            for alias in set([canonical, *aliases]):
                value = unicodedata.normalize('NFKC', alias).casefold()
                found = bool(re.search(r'(?<![a-z0-9])'+re.escape(value)+r'(?![a-z0-9])', question)) if value.isascii() else value in question
                if value and found:
                    mentioned.append(canonical)
                    break
        if not mentioned:
            continue
        def present(filters):
            return {str(v) for f in filters if f.field in rule['fields']
                    for v in (f.value if isinstance(f.value,list) else [f.value])}
        if len(mentioned) == 1:
            scopes = [('current',plan.filters)]
            if plan.comparison_filters is not None:
                scopes.append(('comparison',plan.comparison_filters))
        else:
            scopes = [('either_period',[*plan.filters, *(plan.comparison_filters or [])])]
        for period, filters in scopes:
            lost = [v for v in mentioned if v not in present(filters)]
            if lost:
                missing.append({'fields':rule['fields'],'values':lost,'period':period})
    return missing
