// One way to send a GraphQL query, for every page.
//
// A query goes by GET while its URL is short: the endpoint ETags its answers, so the
// browser revalidates and a refresh that changes nothing costs a 304. A long one goes by
// POST instead: gunicorn refuses a request line over its limit ("Request Line is too
// large (4789 > 4094)"), which a query batching many aliases - Files watching dozens of
// tasks, a list fetching many icons - reached. Mutations always go by POST.

const GQL_MAX_GET_URL = 2000;

function gqlRequest(query, variables) {
    const params = new URLSearchParams({query});
    if (variables && Object.keys(variables).length) params.set('variables', JSON.stringify(variables));
    const url = '/api/graphql?' + params.toString();
    if (url.length <= GQL_MAX_GET_URL) {
        return fetch(url, {headers: {'Accept': 'application/json'}, credentials: 'same-origin'});
    }
    return fetch('/api/graphql', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({query, variables: variables || {}}),
    });
}
