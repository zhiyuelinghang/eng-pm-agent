export const CUSTOM_REQUEST_BODY_KEY = '__request_body__';

export type CustomRequestBodyError = 'invalid_json' | 'object_required';

export function parseCustomRequestBody(text: string): Record<string, unknown> {
	const trimmed = text.trim();
	if (!trimmed) return {};

	let parsed: unknown;
	try {
		parsed = JSON.parse(trimmed) as unknown;
	} catch {
		throw new Error('invalid_json' satisfies CustomRequestBodyError);
	}
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		throw new Error('object_required' satisfies CustomRequestBodyError);
	}
	return parsed as Record<string, unknown>;
}

export function customRequestBodyText(parameters: Record<string, unknown>): string {
	const value = parameters[CUSTOM_REQUEST_BODY_KEY];
	return value && typeof value === 'object' && !Array.isArray(value)
		? JSON.stringify(value, null, 2)
		: '';
}
