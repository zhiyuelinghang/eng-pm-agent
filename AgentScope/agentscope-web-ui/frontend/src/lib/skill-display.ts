import type { Skill } from '@/api';

/** Remove Markdown decoration from a heading used as a UI label. */
export function cleanSkillHeading(value: string): string {
	return value
		.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
		.replace(/[`*_~]/g, '')
		.trim();
}

/**
 * Return the human-readable title declared by SKILL.md.
 *
 * A skill's `name` is its stable technical identifier and must not be used as
 * the primary label when the document already provides a localized H1 title.
 */
export function getSkillDisplayName(skill: Skill): string {
	const heading = /^#\s+(.+?)\s*#*\s*$/m.exec(skill.markdown);
	return heading ? cleanSkillHeading(heading[1]) || skill.name : skill.name;
}
