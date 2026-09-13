import { duration } from '../lib/format'
import type { SkillTraceEntry } from '../lib/incidentModel'

// §8.4a — small, quiet, always visible. The sequence carries the meaning.
export function SkillTrace({ skills }: { skills: SkillTraceEntry[] }) {
  return (
    <div className="skill-trace" aria-label="Skill trace">
      <span className="label">Skills</span>
      {skills.length === 0 ? (
        <span className="muted">No skills invoked yet</span>
      ) : (
        <ol>
          {skills.map((skill, index) => (
            <li
              key={`${skill.name}-${index}`}
              className={`skill-chip skill-${skill.state}`}
              title={skill.rationale ? `Why: ${skill.rationale}` : 'No rationale given'}
            >
              <span className="mono">{skill.name}</span>
              <span className="skill-state">
                {skill.state === 'running' ? 'running' : skill.state === 'failed' ? 'failed' : duration(skill.durationMs)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
