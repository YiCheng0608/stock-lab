import type { HTMLAttributes, ReactNode } from 'react'

import { cx } from './cx'

type CardProps = Omit<HTMLAttributes<HTMLElement>, 'title'> & {
  as?: 'section' | 'article' | 'div'
  eyebrow?: ReactNode
  title?: ReactNode
  titleId?: string
  // Right side of the header: the data-date badge (DESIGN_SYSTEM §7) or a small control.
  aside?: ReactNode
}

// DESIGN_SYSTEM §5 card: card background, 1px border, 16px radius, 24px padding.
export function Card({ as: Tag = 'section', eyebrow, title, titleId, aside, className, children, ...rest }: CardProps) {
  const hasHead = eyebrow != null || title != null || aside != null
  return (
    <Tag className={cx('card', className)} {...rest}>
      {hasHead && (
        <div className="card-head">
          <div className="card-head-text">
            {eyebrow != null && <div className="card-eyebrow">{eyebrow}</div>}
            {title != null && <h3 className="card-title" id={titleId}>{title}</h3>}
          </div>
          {aside != null && <div className="card-aside">{aside}</div>}
        </div>
      )}
      {children}
    </Tag>
  )
}
