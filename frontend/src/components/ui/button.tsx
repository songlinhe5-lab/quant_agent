import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        destructive:
          'bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60',
        outline:
          'border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50',
        secondary:
          'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost:
          'hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2 has-[>svg]:px-3',
        sm: 'h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5',
        lg: 'h-10 rounded-md px-6 has-[>svg]:px-4',
        icon: 'size-9',
        'icon-sm': 'size-8',
        'icon-lg': 'size-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  disableRipple = false,
  onClick,
  children,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
    disableRipple?: boolean
  }) {
  const Comp = asChild ? Slot : 'button'

  const [ripples, setRipples] = React.useState<{ x: number; y: number; size: number; id: number }[]>([])

  const handleClick = (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => {
    if (!disableRipple && !asChild) {
      const rect = e.currentTarget.getBoundingClientRect()
      const rippleSize = Math.max(rect.width, rect.height)
      const x = e.clientX - rect.left - rippleSize / 2
      const y = e.clientY - rect.top - rippleSize / 2
      const id = Date.now()

      setRipples((prev) => [...prev, { x, y, size: rippleSize, id }])

      setTimeout(() => {
        setRipples((prev) => prev.filter((r) => r.id !== id))
      }, 600)
    }
    onClick?.(e)
  }

  return (
    <>
      <style>{`
        @keyframes ripple {
          0% { transform: scale(0); opacity: 0.3; }
          100% { transform: scale(2.5); opacity: 0; }
        }
      `}</style>
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }), !asChild && "relative overflow-hidden")}
      onClick={handleClick}
      {...props}
    >
      {children}
      {!disableRipple && !asChild && ripples.map((r) => (
        <span
          key={r.id}
          className="absolute bg-current rounded-full pointer-events-none"
          style={{
            left: r.x,
            top: r.y,
            width: r.size,
            height: r.size,
            opacity: variant === 'default' || variant === 'destructive' ? 0.25 : 0.1,
            animation: 'ripple 0.6s linear forwards'
          }}
        />
      ))}
    </Comp>
    </>
  )
}

export { Button, buttonVariants }
