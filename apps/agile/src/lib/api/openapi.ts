import { config } from '@/lib/env';
import { WORK_ITEM_STATES, WORK_ITEM_TYPES } from '@/lib/domain/workitem';

/**
 * The OpenAPI document is generated from the same constants the server
 * validates against, so the published contract cannot drift from the code.
 */
export function buildOpenApiDocument(): Record<string, unknown> {
  const workItem = {
    type: 'object',
    properties: {
      id: { type: 'integer' },
      title: { type: 'string' },
      description: { type: 'string', description: 'Markdown.' },
      itemType: { type: 'string', enum: [...WORK_ITEM_TYPES] },
      state: { type: 'string', enum: [...WORK_ITEM_STATES] },
      assigneeLogin: { type: 'string', nullable: true },
      storyPoints: { type: 'integer', nullable: true },
      priority: { type: 'integer', minimum: 1, maximum: 4 },
      sprintId: { type: 'integer', nullable: true },
      tags: { type: 'array', items: { type: 'string' } },
      branchName: { type: 'string', nullable: true },
      commitCount: { type: 'integer' },
      pullRequests: { type: 'array', items: { $ref: '#/components/schemas/PullRequestLink' } },
      createdBy: { type: 'string' },
      createdAt: { type: 'string', format: 'date-time' },
      updatedAt: { type: 'string', format: 'date-time' },
    },
  };

  const createInput = {
    type: 'object',
    required: ['title'],
    properties: {
      title: { type: 'string', maxLength: 300 },
      description: { type: 'string', default: '' },
      itemType: { type: 'string', enum: [...WORK_ITEM_TYPES], default: 'Story' },
      state: { type: 'string', enum: [...WORK_ITEM_STATES], default: 'New' },
      assigneeLogin: { type: 'string', nullable: true },
      storyPoints: { type: 'integer', nullable: true },
      priority: { type: 'integer', minimum: 1, maximum: 4, default: 2 },
      sprintId: { type: 'integer', nullable: true },
      tags: { type: 'array', items: { type: 'string' }, default: [] },
    },
  };

  const errorSchema = {
    type: 'object',
    properties: {
      error: {
        type: 'object',
        properties: {
          code: { type: 'string' },
          message: { type: 'string' },
          fields: { type: 'object', additionalProperties: { type: 'array', items: { type: 'string' } } },
        },
      },
    },
  };

  const idParam = {
    name: 'id',
    in: 'path',
    required: true,
    schema: { type: 'integer' },
  };

  return {
    openapi: '3.1.0',
    info: {
      title: `${config.boardTitle} API`,
      version: '1.0.0',
      description:
        `Work-item board for ${config.teamLabel}.\n\n` +
        'Authenticate with a board-issued token: `Authorization: Bearer iag_...`. ' +
        'Create one in the UI under **Tokens**. A token acts as the human who issued it, ' +
        'so everything it does is attributed to them in the item history. ' +
        'This is the same API the web UI uses — there is no separate internal surface.',
    },
    servers: [{ url: config.appUrl }],
    security: [{ bearerAuth: [] }],
    components: {
      securitySchemes: {
        bearerAuth: { type: 'http', scheme: 'bearer', description: 'A board API token (iag_...).' },
      },
      schemas: {
        WorkItem: workItem,
        CreateWorkItem: createInput,
        PullRequestLink: {
          type: 'object',
          properties: {
            id: { type: 'integer' },
            repoFullName: { type: 'string' },
            prNumber: { type: 'integer' },
            url: { type: 'string' },
            title: { type: 'string' },
            prState: { type: 'string' },
            merged: { type: 'boolean' },
            checksState: { type: 'string', nullable: true },
          },
        },
        Sprint: {
          type: 'object',
          properties: {
            id: { type: 'integer' },
            name: { type: 'string' },
            goal: { type: 'string' },
            startsOn: { type: 'string', format: 'date' },
            endsOn: { type: 'string', format: 'date' },
          },
        },
        Error: errorSchema,
      },
    },
    paths: {
      '/api/v1/items': {
        get: {
          summary: 'List work items',
          parameters: [
            { name: 'state', in: 'query', schema: { type: 'string', enum: [...WORK_ITEM_STATES] } },
            { name: 'type', in: 'query', schema: { type: 'string', enum: [...WORK_ITEM_TYPES] } },
            { name: 'assignee', in: 'query', schema: { type: 'string' }, description: 'A GitHub login, or "me".' },
            { name: 'sprintId', in: 'query', schema: { type: 'string' }, description: '"all", "none", or a sprint id.' },
            { name: 'tag', in: 'query', schema: { type: 'string' } },
            { name: 'q', in: 'query', schema: { type: 'string' }, description: 'Free text over title and description.' },
            { name: 'limit', in: 'query', schema: { type: 'integer', maximum: 500 } },
            { name: 'offset', in: 'query', schema: { type: 'integer' } },
          ],
          responses: {
            200: {
              description: 'Matching items.',
              content: {
                'application/json': {
                  schema: {
                    type: 'object',
                    properties: {
                      items: { type: 'array', items: { $ref: '#/components/schemas/WorkItem' } },
                      count: { type: 'integer' },
                    },
                  },
                },
              },
            },
          },
        },
        post: {
          summary: 'Create one work item, or many at once',
          description:
            'Send a single work item object, or `{ "items": [ ... ] }` to create up to 100 in one call. ' +
            'Send an `Idempotency-Key` header to make a retry safe.',
          parameters: [
            {
              name: 'Idempotency-Key',
              in: 'header',
              required: false,
              schema: { type: 'string' },
              description: 'Replays the first response for a repeated key. Reusing a key with a different body is a 409.',
            },
          ],
          requestBody: {
            required: true,
            content: {
              'application/json': {
                schema: {
                  oneOf: [
                    { $ref: '#/components/schemas/CreateWorkItem' },
                    {
                      type: 'object',
                      required: ['items'],
                      properties: {
                        items: {
                          type: 'array', minItems: 1, maxItems: 100,
                          items: { $ref: '#/components/schemas/CreateWorkItem' },
                        },
                      },
                    },
                  ],
                },
              },
            },
          },
          responses: {
            201: { description: 'Created.' },
            409: { description: 'Idempotency-Key reused with a different body.', content: { 'application/json': { schema: errorSchema } } },
            422: { description: 'Validation failed.', content: { 'application/json': { schema: errorSchema } } },
          },
        },
      },
      '/api/v1/items/{id}': {
        get: { summary: 'Get one item with comments, history and attachments', parameters: [idParam], responses: { 200: { description: 'The item.' }, 404: { description: 'Not found.' } } },
        patch: {
          summary: 'Update fields, including state',
          parameters: [idParam],
          requestBody: { required: true, content: { 'application/json': { schema: { $ref: '#/components/schemas/CreateWorkItem' } } } },
          responses: {
            200: { description: 'Updated.' },
            409: { description: 'Illegal state transition.', content: { 'application/json': { schema: errorSchema } } },
          },
        },
        delete: { summary: 'Delete permanently (prefer state "Removed")', parameters: [idParam], responses: { 200: { description: 'Deleted.' } } },
      },
      '/api/v1/items/{id}/move': {
        post: {
          summary: 'Transition state',
          description: 'Rejects illegal transitions with 409. New→Active→Resolved→Closed; Closed can reactivate to Active.',
          parameters: [idParam],
          requestBody: {
            required: true,
            content: {
              'application/json': {
                schema: {
                  type: 'object', required: ['toState'],
                  properties: {
                    toState: { type: 'string', enum: [...WORK_ITEM_STATES] },
                    orderedIds: { type: 'array', items: { type: 'integer' }, description: 'Optional board ordering for the destination column.' },
                  },
                },
              },
            },
          },
          responses: { 200: { description: 'Moved.' }, 409: { description: 'Illegal transition.' } },
        },
      },
      '/api/v1/items/{id}/start-work': {
        post: {
          summary: 'Activate and claim the item, and branch it when its type branches',
          description:
            'Requires a signed-in session (branch creation uses the user\'s GitHub token). ' +
            'The state change is applied first and is never rolled back by a branch failure. ' +
            'A branch is created for Story and Bug items only: Spike and Task work does not ' +
            'live in git, so they are activated and assigned with no branch and the response ' +
            'carries branch.status "skipped". Send {"branch": true} or {"branch": false} to ' +
            'override that default in either direction.',
          parameters: [idParam],
          requestBody: {
            required: false,
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  additionalProperties: false,
                  properties: {
                    activate: { type: 'boolean', description: 'Set false to claim/branch without moving the item to Active.' },
                    branch: { type: 'boolean', description: 'Force branch creation on or off, overriding the item-type default.' },
                    repo: { type: 'string', description: 'Branch in a non-primary repo the board follows.' },
                  },
                },
              },
            },
          },
          responses: {
            200: { description: 'Item, plus branch status ("created", "existing", "skipped", "disabled" or "failed").' },
            422: { description: 'Unrecognized or invalid field in the body.' },
          },
        },
      },
      '/api/v1/items/{id}/links': {
        post: {
          summary: 'Link a pull request',
          parameters: [idParam],
          requestBody: {
            required: true,
            content: { 'application/json': { schema: { type: 'object', required: ['reference'], properties: { reference: { type: 'string', description: 'PR URL, owner/repo#123, or 123.' } } } } },
          },
          responses: { 201: { description: 'Linked.' } },
        },
        delete: { summary: 'Unlink a pull request', parameters: [idParam, { name: 'linkId', in: 'query', required: true, schema: { type: 'integer' } }], responses: { 200: { description: 'Unlinked.' } } },
      },
      '/api/v1/items/{id}/comments': {
        get: { summary: 'List comments', parameters: [idParam], responses: { 200: { description: 'Comments.' } } },
        post: {
          summary: 'Add a comment',
          parameters: [idParam],
          requestBody: { required: true, content: { 'application/json': { schema: { type: 'object', required: ['body'], properties: { body: { type: 'string' } } } } } },
          responses: { 201: { description: 'Created.' } },
        },
      },
      '/api/v1/sprints': {
        get: { summary: 'List sprints with their stats', responses: { 200: { description: 'Sprints and their stats.' } } },
        post: {
          summary: 'Create a sprint',
          requestBody: {
            required: true,
            content: { 'application/json': { schema: { type: 'object', required: ['name', 'startsOn', 'endsOn'], properties: { name: { type: 'string' }, goal: { type: 'string' }, startsOn: { type: 'string', format: 'date' }, endsOn: { type: 'string', format: 'date' } } } } },
          },
          responses: { 201: { description: 'Created.' } },
        },
      },
      '/api/v1/sprints/{id}': {
        patch: { summary: 'Update a sprint', parameters: [idParam], responses: { 200: { description: 'Updated.' } } },
        delete: { summary: 'Delete a sprint (its items return to the backlog)', parameters: [idParam], responses: { 200: { description: 'Deleted.' } } },
      },
      '/api/v1/members': { get: { summary: 'Team members (assignee candidates)', responses: { 200: { description: 'Members.' } } } },
      '/api/v1/prs': { get: { summary: 'Open pull requests, annotated with AB#<id> references', responses: { 200: { description: 'Pull requests.' } } } },
      '/api/v1/tokens': {
        get: { summary: 'List your API tokens', responses: { 200: { description: 'Tokens (never their values).' } } },
        post: { summary: 'Create an API token (session only)', responses: { 201: { description: 'The token, shown once.' } } },
      },
      '/api/v1/tokens/{id}': { delete: { summary: 'Revoke a token', parameters: [idParam], responses: { 200: { description: 'Revoked.' } } } },
    },
  };
}
