import type { ButtonHTMLAttributes } from 'react'

import { cx } from './cx'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: 'md' | 'sm'
}

// DESIGN_SYSTEM §5: at most one primary button per screen; secondary and ghost for everything else.
export function Button({ variant = 'secondary', size = 'md', type = 'button', className, ...rest }: ButtonProps) {
  return <button type={type} className={cx('btn', `btn-${variant}`, size === 'sm' && 'btn-sm', className)} {...rest} />
}
