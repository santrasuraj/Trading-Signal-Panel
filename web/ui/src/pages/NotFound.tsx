import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/feedback'

export default function NotFound() {
  return (
    <div className="card mx-auto mt-10 max-w-lg">
      <EmptyState title="Page not found" action={<Link className="link text-[13px]" to="/">Back to Overview</Link>}>
        The address doesn't match any page. Press Ctrl K to search stocks, strategies and pages.
      </EmptyState>
    </div>
  )
}
