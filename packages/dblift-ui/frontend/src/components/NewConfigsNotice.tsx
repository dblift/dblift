interface Props {
  count: number;
  onAdd: () => void;
  onDismiss: () => void;
}

/** Shown after a switch or a pull brought configs that are not in the project list. */
export default function NewConfigsNotice({ count, onAdd, onDismiss }: Props) {
  return (
    <div className="notice newconfigs" role="status">
      <span>
        {count === 1
          ? "1 configuration on this branch is not a project yet."
          : `${count} configurations on this branch are not projects yet.`}
      </span>
      <button className="button" onClick={onAdd}>
        Add
      </button>
      <button className="button button--quiet" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}
